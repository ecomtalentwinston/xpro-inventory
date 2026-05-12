import pandas as pd
import numpy as np
import io
import base64

def parse_uploaded_file(uploaded_file):
    """
    Parse an uploaded CSV or Excel file.
    
    Parameters:
    -----------
    uploaded_file : streamlit.UploadedFile
        The file uploaded by the user
        
    Returns:
    --------
    pandas.DataFrame
        The parsed data as a DataFrame
    """
    try:
        # Get the file extension
        file_extension = uploaded_file.name.split('.')[-1].lower()
        
        if file_extension == 'csv':
            df = pd.read_csv(uploaded_file)
        elif file_extension in ['xls', 'xlsx']:
            df = pd.read_excel(uploaded_file)
        else:
            raise ValueError(f"Unsupported file format: {file_extension}. Please upload a CSV or Excel file.")
        
        return df
    except Exception as e:
        raise Exception(f"Error parsing the uploaded file: {str(e)}")

def extract_sales_velocity(df, column_name=None):
    """
    Extract sales velocity from the uploaded data.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The data containing sales information
    column_name : str, optional
        The name of the column containing sales velocity
        
    Returns:
    --------
    float
        The calculated or extracted sales velocity
    """
    try:
        # If column name is provided, try to extract directly
        if column_name and column_name in df.columns:
            velocity = df[column_name].mean()
            if pd.notnull(velocity) and velocity > 0:
                return float(velocity)
        
        # Otherwise look for columns that might contain velocity information
        potential_columns = [col for col in df.columns if any(keyword in col.lower() 
                                                            for keyword in ['velocity', 'sales', 'rate', 'units', 'daily'])]
        
        for col in potential_columns:
            if df[col].dtype in [np.float64, np.int64, np.float32, np.int32]:
                avg_value = df[col].mean()
                if pd.notnull(avg_value) and avg_value > 0:
                    return float(avg_value)
        
        # If no suitable column found, return a default
        return 0.0
    except Exception as e:
        raise Exception(f"Error extracting sales velocity: {str(e)}")

def extract_initial_inventory(df, column_name=None):
    """
    Extract initial inventory from the uploaded data.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The data containing inventory information
    column_name : str, optional
        The name of the column containing inventory
        
    Returns:
    --------
    int
        The extracted initial inventory
    """
    try:
        # If column name is provided, try to extract directly
        if column_name and column_name in df.columns:
            inventory = df[column_name].iloc[0]
            if pd.notnull(inventory) and inventory >= 0:
                return int(inventory)
        
        # Otherwise look for columns that might contain inventory information
        potential_columns = [col for col in df.columns if any(keyword in col.lower() 
                                                             for keyword in ['inventory', 'stock', 'on hand', 'quantity'])]
        
        for col in potential_columns:
            if df[col].dtype in [np.float64, np.int64, np.float32, np.int32]:
                first_value = df[col].iloc[0]
                if pd.notnull(first_value) and first_value >= 0:
                    return int(first_value)
        
        # If no suitable column found, return a default
        return 0
    except Exception as e:
        raise Exception(f"Error extracting initial inventory: {str(e)}")

def extract_delivery_schedule(df):
    """
    Extract delivery schedule from the uploaded data.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The data containing delivery information
        
    Returns:
    --------
    list
        List of tuples (day, quantity) for scheduled deliveries
    """
    try:
        # Look for date/delivery columns
        date_columns = [col for col in df.columns if any(keyword in col.lower() 
                                                        for keyword in ['date', 'day', 'time'])]
        
        quantity_columns = [col for col in df.columns if any(keyword in col.lower() 
                                                           for keyword in ['quantity', 'amount', 'units', 'delivery'])]
        
        if date_columns and quantity_columns:
            date_col = date_columns[0]
            qty_col = quantity_columns[0]
            
            # Make sure both columns have valid data
            valid_rows = df[[date_col, qty_col]].dropna()
            
            # Convert dates to days from today
            if pd.api.types.is_datetime64_any_dtype(valid_rows[date_col]):
                # Already datetime
                dates = valid_rows[date_col]
            else:
                # Try to convert to datetime
                try:
                    dates = pd.to_datetime(valid_rows[date_col])
                except:
                    # If conversion fails, assume it's already days
                    return [(int(row[date_col]), int(row[qty_col])) 
                            for _, row in valid_rows.iterrows() 
                            if pd.notnull(row[date_col]) and pd.notnull(row[qty_col])]
            
            # Calculate days from today
            today = pd.Timestamp.now().normalize()
            days_from_today = [(date - today).days for date in dates]
            
            # Create delivery schedule
            deliveries = [(max(0, day), int(qty)) for day, qty in zip(days_from_today, valid_rows[qty_col])]
            
            return deliveries
            
        # If no suitable columns found, return empty list
        return []
    except Exception as e:
        raise Exception(f"Error extracting delivery schedule: {str(e)}")

def extract_seasonality_factors(df):
    """
    Extract seasonality factors from the uploaded data.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The data containing seasonality information
        
    Returns:
    --------
    dict
        Dictionary mapping months (1-12) to seasonality factors
    """
    try:
        # Look for month/seasonality columns
        month_columns = [col for col in df.columns if any(keyword in col.lower() 
                                                         for keyword in ['month', 'period'])]
        
        factor_columns = [col for col in df.columns if any(keyword in col.lower() 
                                                         for keyword in ['factor', 'multiplier', 'seasonality', 'adjustment'])]
        
        if month_columns and factor_columns:
            month_col = month_columns[0]
            factor_col = factor_columns[0]
            
            # Make sure both columns have valid data
            valid_rows = df[[month_col, factor_col]].dropna()
            
            # Create seasonality dictionary
            seasonality = {}
            
            for _, row in valid_rows.iterrows():
                month = row[month_col]
                factor = row[factor_col]
                
                # Handle different month formats
                if isinstance(month, str):
                    # Try to convert month name to number
                    try:
                        month = pd.to_datetime(month, format='%B').month
                    except:
                        try:
                            month = pd.to_datetime(month, format='%b').month
                        except:
                            # If still string, skip this row
                            continue
                
                if 1 <= month <= 12 and pd.notnull(factor) and factor > 0:
                    seasonality[int(month)] = float(factor)
            
            return seasonality
            
        # If no suitable columns found, return empty dict
        return {}
    except Exception as e:
        raise Exception(f"Error extracting seasonality factors: {str(e)}")

def generate_sample_data():
    """
    Generate a sample data CSV for users to download as a template.
    
    Returns:
    --------
    str
        Base64 encoded CSV data for download
    """
    # Create sample data
    sample_data = {
        'Date': pd.date_range(start='2023-01-01', periods=12, freq='MS'),
        'Sales_Velocity': [45.2, 46.5, 44.3, 47.1, 49.8, 48.2, 47.6, 45.9, 46.3, 48.7, 51.2, 49.5],
        'Inventory': [1000, 950, 900, 850, 800, 750, 700, 650, 600, 550, 500, 450],
        'Delivery_Date': ['2023-01-15', '2023-02-15', '2023-03-15', '2023-04-15', '2023-05-15', 
                          '2023-06-15', '2023-07-15', '2023-08-15', '2023-09-15', '2023-10-15', 
                          '2023-11-15', '2023-12-15'],
        'Delivery_Quantity': [2500, 2600, 2550, 2700, 2800, 2750, 2650, 2600, 2700, 2850, 3000, 2900],
        'Month': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        'Seasonality_Factor': [0.8, 0.9, 1.0, 1.1, 1.2, 1.2, 1.1, 1.0, 1.1, 1.3, 1.5, 1.3]
    }
    
    df = pd.DataFrame(sample_data)
    
    # Convert to CSV
    csv = df.to_csv(index=False)
    
    # Encode as base64
    b64 = base64.b64encode(csv.encode()).decode()
    
    return b64
