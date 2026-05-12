import os
import json
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from io import StringIO

# Custom JSON encoder to handle NumPy types
class NumpyJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, datetime):
            return obj.isoformat()
        return super(NumpyJSONEncoder, self).default(obj)

# Create SQLAlchemy engine and session
# Falls back to a local SQLite file if DATABASE_URL is not set (local development)
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///forecasts.db')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

class ForecastSimulation(Base):
    """
    Database model for stored forecast simulations.
    """
    __tablename__ = 'forecast_simulations'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    asin = Column(String(20), nullable=True)  # Amazon Standard Identification Number
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Core parameters
    initial_inventory = Column(Integer, nullable=False)
    sales_velocity = Column(Float, nullable=False)
    lead_time = Column(Integer, nullable=False)
    safety_stock_days = Column(Integer, nullable=False)
    start_date = Column(DateTime, nullable=False)
    forecast_days = Column(Integer, nullable=False)
    
    # Options
    use_seasonality = Column(Boolean, default=False)
    dynamic_reorder = Column(Boolean, default=True)
    
    # Serialized data
    deliveries = Column(Text)  # JSON string of list of tuples [(day, quantity),...]
    seasonality_factors = Column(Text)  # JSON string of dict {month: factor,...}
    forecast_results = Column(Text)  # JSON string of forecast dataframe
    analytics = Column(Text)  # JSON string of analytics dict

    def set_deliveries(self, deliveries_list):
        """Set deliveries as JSON string"""
        self.deliveries = json.dumps(deliveries_list, cls=NumpyJSONEncoder)
    
    def get_deliveries(self):
        """Get deliveries as Python list of tuples"""
        if not self.deliveries:
            return []
        return json.loads(self.deliveries)
    
    def set_seasonality_factors(self, factors_dict):
        """Set seasonality factors as JSON string"""
        # Convert keys to strings for JSON serialization
        str_dict = {str(k): v for k, v in factors_dict.items()}
        self.seasonality_factors = json.dumps(str_dict, cls=NumpyJSONEncoder)
    
    def get_seasonality_factors(self):
        """Get seasonality factors as Python dict"""
        if not self.seasonality_factors:
            return {}
        # Convert string keys back to integers
        factors = json.loads(self.seasonality_factors)
        return {int(k): v for k, v in factors.items()}
    
    def set_forecast_results(self, df):
        """Serialize pandas DataFrame to JSON"""
        # Convert dates to string format before serialization
        df_copy = df.copy()
        df_copy['date'] = df_copy['date'].dt.strftime('%Y-%m-%d')
        
        # Convert NumPy data types to Python native types
        for col in df_copy.select_dtypes(include=[np.number]).columns:
            df_copy[col] = df_copy[col].astype(float)
            
        self.forecast_results = df_copy.to_json(orient='records', date_format='iso')
    
    def get_forecast_results(self):
        """Deserialize JSON to pandas DataFrame"""
        if not self.forecast_results:
            return None
        # Use StringIO to wrap the JSON string to avoid deprecation warning
        df = pd.read_json(StringIO(self.forecast_results), orient='records')
        # Convert date strings back to datetime
        df['date'] = pd.to_datetime(df['date'])
        return df
    
    def set_analytics(self, analytics_dict):
        """Set analytics as JSON string"""
        self.analytics = json.dumps(analytics_dict, cls=NumpyJSONEncoder)
    
    def get_analytics(self):
        """Get analytics as Python dict"""
        if not self.analytics:
            return {}
        return json.loads(self.analytics)

# Create tables
Base.metadata.create_all(engine)

def save_forecast(name, asin, description, parameters, forecast_df, analytics):
    """
    Save a forecast simulation to the database.
    
    Parameters:
    -----------
    name : str
        Name of the forecast simulation
    asin : str
        Amazon Standard Identification Number for the product
    description : str
        Optional description of the simulation
    parameters : dict
        Dictionary containing all forecast parameters
    forecast_df : pandas.DataFrame
        The forecast results dataframe
    analytics : dict
        Dictionary of forecast analytics
    
    Returns:
    --------
    int
        ID of the saved forecast
    """
    session = None
    try:
        session = Session()

        # Convert datetime to string for database storage
        parameters_copy = parameters.copy()
        if 'start_date' in parameters_copy and isinstance(parameters_copy['start_date'], datetime):
            # Store as is in the model (SQLAlchemy handles DateTime conversion)
            start_date = parameters_copy['start_date']
        else:
            # Fallback if start_date is missing or not a datetime
            start_date = datetime.now()
        
        # Create new forecast record
        forecast = ForecastSimulation(
            name=name,
            asin=asin,
            description=description,
            initial_inventory=parameters['initial_inventory'],
            sales_velocity=parameters['sales_velocity'],
            lead_time=parameters['lead_time'],
            safety_stock_days=parameters['safety_stock_days'],
            start_date=start_date,
            forecast_days=parameters['days'],
            use_seasonality=parameters['use_seasonality'],
            dynamic_reorder=parameters['dynamic_reorder']
        )
        
        # Set complex data
        forecast.set_deliveries(parameters['deliveries'])
        forecast.set_seasonality_factors(parameters['seasonality_factors'])
        forecast.set_forecast_results(forecast_df)
        
        # Make sure analytics doesn't contain datetime objects
        analytics_copy = {}
        for key, value in analytics.items():
            if isinstance(value, datetime):
                analytics_copy[key] = value.isoformat()
            else:
                analytics_copy[key] = value
                
        forecast.set_analytics(analytics_copy)
        
        # Save to database
        session.add(forecast)
        session.commit()
        
        # Get ID of new record
        forecast_id = forecast.id
        
        session.close()
        return forecast_id
    
    except Exception as e:
        if session:
            session.rollback()
            session.close()
        
        # Provide more detailed error information
        error_msg = str(e)
        if "is not JSON serializable" in error_msg:
            # If it's a JSON serialization error, try to identify the problematic value
            try:
                for key, value in analytics.items():
                    if isinstance(value, (np.integer, np.floating, np.ndarray)):
                        analytics[key] = value.item() if hasattr(value, 'item') else value.tolist()
                
                # Try again with converted values
                if 'session' in locals():  # Make sure we have a fresh session
                    session = Session()
                    forecast = ForecastSimulation(
                        name=name,
                        asin=asin,
                        description=description,
                        initial_inventory=int(parameters['initial_inventory']),
                        sales_velocity=float(parameters['sales_velocity']),
                        lead_time=int(parameters['lead_time']),
                        safety_stock_days=int(parameters['safety_stock_days']),
                        start_date=start_date,
                        forecast_days=int(parameters['days']),
                        use_seasonality=bool(parameters['use_seasonality']),
                        dynamic_reorder=bool(parameters['dynamic_reorder'])
                    )
                    
                    # Set complex data
                    forecast.set_deliveries(parameters['deliveries'])
                    forecast.set_seasonality_factors(parameters['seasonality_factors'])
                    forecast.set_forecast_results(forecast_df)
                    forecast.set_analytics(analytics)
                    
                    # Save to database
                    session.add(forecast)
                    session.commit()
                    
                    # Get ID of new record
                    forecast_id = forecast.id
                    
                    session.close()
                    return forecast_id
            except Exception as inner_e:
                # If the retry also fails, provide both errors
                raise Exception(f"Error saving forecast: {error_msg}. Retry failed: {str(inner_e)}")
        
        # If not a JSON error or retry failed, raise the original error
        raise Exception(f"Error saving forecast: {error_msg}")

def get_forecasts():
    """
    Get all saved forecasts.

    Returns:
    --------
    list
        List of forecast simulations (basic info only)
    """
    session = None
    try:
        session = Session()
        forecasts = session.query(
            ForecastSimulation.id,
            ForecastSimulation.name,
            ForecastSimulation.asin,
            ForecastSimulation.description,
            ForecastSimulation.created_at,
            ForecastSimulation.initial_inventory,
            ForecastSimulation.sales_velocity,
            ForecastSimulation.forecast_days
        ).order_by(ForecastSimulation.created_at.desc()).all()
        
        result = [
            {
                'id': f.id,
                'name': f.name,
                'asin': f.asin,
                'description': f.description,
                'created_at': f.created_at,
                'initial_inventory': f.initial_inventory,
                'sales_velocity': f.sales_velocity,
                'forecast_days': f.forecast_days
            }
            for f in forecasts
        ]
        
        session.close()
        return result
    
    except Exception as e:
        if session:
            session.close()
        raise Exception(f"Error retrieving forecasts: {str(e)}")

def get_forecast(forecast_id):
    """
    Get a specific forecast by ID.

    Parameters:
    -----------
    forecast_id : int
        ID of the forecast to retrieve

    Returns:
    --------
    dict
        Dictionary containing all forecast data
    """
    session = None
    try:
        session = Session()
        forecast = session.query(ForecastSimulation).filter_by(id=forecast_id).first()
        
        if not forecast:
            session.close()
            raise Exception(f"Forecast with ID {forecast_id} not found")
        
        # Get analytics and ensure it's a proper dictionary
        analytics = forecast.get_analytics()
        if not isinstance(analytics, dict):
            analytics = {}
            
        # Build result dictionary
        result = {
            'id': forecast.id,
            'name': forecast.name,
            'asin': forecast.asin,
            'description': forecast.description,
            'created_at': forecast.created_at,
            'parameters': {
                'initial_inventory': forecast.initial_inventory,
                'sales_velocity': forecast.sales_velocity,
                'lead_time': forecast.lead_time,
                'safety_stock_days': forecast.safety_stock_days,
                'start_date': forecast.start_date,
                'days': forecast.forecast_days,
                'use_seasonality': forecast.use_seasonality,
                'dynamic_reorder': forecast.dynamic_reorder,
                'deliveries': forecast.get_deliveries(),
                'seasonality_factors': forecast.get_seasonality_factors()
            },
            'forecast_df': forecast.get_forecast_results(),
            'analytics': analytics
        }
        
        # Add weighted velocity parameters if they exist
        try:
            # Get additional parameters from analytics
            if 'use_weighted_velocity' in analytics:
                result['parameters']['use_weighted_velocity'] = analytics['use_weighted_velocity']
            if 'period_sales' in analytics:
                result['parameters']['period_sales'] = analytics['period_sales']
            if 'period_weights' in analytics:
                result['parameters']['period_weights'] = analytics['period_weights']
        except:
            # Silently continue if there's an issue with optional parameters
            pass
        
        session.close()
        return result
    
    except Exception as e:
        if session:
            session.close()
        raise Exception(f"Error retrieving forecast: {str(e)}")

def get_forecasts_by_asin(asin):
    """
    Get all saved forecasts for a specific ASIN.

    Parameters:
    -----------
    asin : str
        Amazon Standard Identification Number to search for

    Returns:
    --------
    list
        List of forecast simulations for the ASIN (basic info only)
    """
    session = None
    try:
        session = Session()
        forecasts = session.query(
            ForecastSimulation.id,
            ForecastSimulation.name,
            ForecastSimulation.asin,
            ForecastSimulation.description,
            ForecastSimulation.created_at,
            ForecastSimulation.initial_inventory,
            ForecastSimulation.sales_velocity,
            ForecastSimulation.forecast_days
        ).filter(ForecastSimulation.asin == asin).order_by(ForecastSimulation.created_at.desc()).all()
        
        result = [
            {
                'id': f.id,
                'name': f.name,
                'asin': f.asin,
                'description': f.description,
                'created_at': f.created_at,
                'initial_inventory': f.initial_inventory,
                'sales_velocity': f.sales_velocity,
                'forecast_days': f.forecast_days
            }
            for f in forecasts
        ]
        
        session.close()
        return result
    
    except Exception as e:
        if session:
            session.close()
        raise Exception(f"Error retrieving forecasts for ASIN {asin}: {str(e)}")

def get_unique_asins():
    """
    Get all unique ASINs that have saved forecasts.

    Returns:
    --------
    list
        List of unique ASINs
    """
    session = None
    try:
        session = Session()
        asins = session.query(ForecastSimulation.asin).filter(
            ForecastSimulation.asin.isnot(None),
            ForecastSimulation.asin != ''
        ).distinct().all()
        
        result = [asin[0] for asin in asins if asin[0]]
        session.close()
        return sorted(result)
    
    except Exception as e:
        if session:
            session.close()
        raise Exception(f"Error retrieving unique ASINs: {str(e)}")

def delete_forecast(forecast_id):
    """
    Delete a forecast by ID.

    Parameters:
    -----------
    forecast_id : int
        ID of the forecast to delete

    Returns:
    --------
    bool
        True if successful
    """
    session = None
    try:
        session = Session()
        forecast = session.query(ForecastSimulation).filter_by(id=forecast_id).first()
        
        if not forecast:
            session.close()
            raise Exception(f"Forecast with ID {forecast_id} not found")
        
        session.delete(forecast)
        session.commit()
        session.close()
        
        return True
    
    except Exception as e:
        if session:
            session.rollback()
            session.close()
        raise Exception(f"Error deleting forecast: {str(e)}")