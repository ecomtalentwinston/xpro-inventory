import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import math

def run_forecast(initial_inventory, base_velocity, start_date, days=180, 
                deliveries=None, lead_time=80, safety_stock_days=15, 
                use_seasonality=False, seasonality_factors=None, 
                dynamic_reorder=False, reorder_policy='R_S', cycle_cover_days=35,
                min_days_between_orders=30, moq=0, casepack=1, service_level_z=1.65,
                demand_std_dev=None, use_service_level_safety=False, stockout_mode='lost_sales'):
    """
    Run a daily inventory forecast simulation with professional inventory management.
    
    Parameters:
    -----------
    initial_inventory : int
        Starting inventory quantity
    base_velocity : float
        Base daily sales velocity (units/day)
    start_date : datetime
        Starting date for the forecast
    days : int
        Number of days to forecast (default: 180)
    deliveries : list of tuples
        List of scheduled deliveries as (day, quantity)
    lead_time : int
        Lead time in days for new orders (default: 80)
    safety_stock_days : int
        Safety stock in days (default: 15) - only used if use_service_level_safety=False
    use_seasonality : bool
        Whether to apply seasonality factors (default: False)
    seasonality_factors : dict
        Dictionary mapping month numbers (1-12) to seasonality multipliers
    dynamic_reorder : bool
        Whether to generate reorder recommendations (default: False)
    reorder_policy : str
        Reorder policy: 'R_S' (order-up-to), 's_Q' (fixed lot), 'EOQ' (default: 'R_S')
    cycle_cover_days : int
        Cycle coverage in days for order-up-to level (default: 35)
    min_days_between_orders : int
        Minimum days between reorders (default: 30)
    moq : int
        Minimum order quantity (default: 0)
    casepack : int
        Casepack multiple for orders (default: 1)
    service_level_z : float
        Z-score for service level safety stock (default: 1.65 = ~95%)
    demand_std_dev : float
        Daily demand standard deviation (default: None, estimated as 20% of base_velocity)
    use_service_level_safety : bool
        Use service level safety stock instead of days-based (default: False)
    stockout_mode : str
        'lost_sales' or 'backorders' (default: 'lost_sales')
    
    Returns:
    --------
    pandas.DataFrame
        Daily forecast with inventory levels and events
    """
    # Initialize data structures
    inventory = initial_inventory
    backorder_quantity = 0.0  # Track backorders if using backorder mode
    forecast_dates = [start_date + timedelta(days=i) for i in range(days)]
    
    # Convert deliveries to a dictionary keyed by day
    delivery_dict = {}
    if deliveries:
        for day, qty in deliveries:
            if day < days:
                delivery_dict[day] = qty
    
    # Prepare DataFrame to store the forecast results
    forecast_data = {
        'date': forecast_dates,
        'day': list(range(days)),
        'inventory': np.zeros(days),
        'velocity': np.zeros(days),
        'delivery': np.zeros(days),
        'delivery_amount': np.zeros(days),
        'reorder_trigger': np.zeros(days, dtype=bool),
        'reorder_amount': np.zeros(days),
        'reorder_arrival_day': np.zeros(days, dtype=int),
        'inventory_position': np.zeros(days),
        'on_order': np.zeros(days),
        'safety_stock': np.zeros(days),
        'reorder_point': np.zeros(days),
        'lost_sales': np.zeros(days),
        'backorders': np.zeros(days),
        'fill_rate': np.zeros(days)
    }
    
    # If seasonality factors are not provided, use default (no seasonality)
    if seasonality_factors is None:
        seasonality_factors = {month: 1.0 for month in range(1, 13)}
    
    # Estimate demand standard deviation if not provided
    if demand_std_dev is None:
        demand_std_dev = base_velocity * 0.2  # Default: 20% of mean demand
    
    # Function to get daily sales velocity with seasonality
    def get_daily_velocity(date):
        if use_seasonality:
            month = date.month
            return base_velocity * seasonality_factors.get(month, 1.0)
        return base_velocity
    
    # A. Lead time demand calculation with proper seasonality
    def lead_time_demand(start_day, L):
        """Calculate expected demand over next L days with proper seasonality"""
        total = 0.0
        for k in range(1, L + 1):
            if start_day + k < days:
                future_date = forecast_dates[start_day + k]
                total += get_daily_velocity(future_date)
            else:
                # Extrapolate with current seasonality if beyond forecast horizon
                total += get_daily_velocity(forecast_dates[min(start_day + k, days - 1)])
        return total
    
    # B. Safety stock calculation functions
    def calculate_safety_stock_days(daily_velocity):
        """Simple days-based safety stock"""
        return daily_velocity * safety_stock_days
    
    def calculate_safety_stock_service_level(daily_velocity, L):
        """Service level based safety stock using z-score"""
        # SS = z * sqrt(σ_d^2 * L + d^2 * σ_L^2)
        # Assuming σ_L = 0 (deterministic lead time)
        variance_during_lt = demand_std_dev**2 * L
        return service_level_z * math.sqrt(variance_during_lt)
    
    # C. Round to casepack/MOQ
    def round_to_casepack(quantity, casepack_size, moq_size):
        """Round quantity to casepack multiple and ensure MOQ"""
        if quantity <= 0:
            return 0
        
        # Round up to casepack multiple
        rounded = math.ceil(quantity / casepack_size) * casepack_size
        
        # Ensure MOQ
        return max(rounded, moq_size)
    
    # Track reorders to be scheduled
    pending_deliveries = {}  # day -> quantity
    
    # Run the daily simulation
    for i in range(days):
        current_date = forecast_dates[i]
        
        # Calculate today's velocity
        today_velocity = get_daily_velocity(current_date)
        
        # Add any scheduled or dynamic deliveries for today
        delivery_today = 0
        if i in delivery_dict:
            delivery_today += delivery_dict[i]
        if i in pending_deliveries:
            delivery_today += pending_deliveries[i]
        
        # Handle stockout mode
        if stockout_mode == 'backorders':
            # In backorder mode, fulfill backorders first
            if delivery_today > 0 and backorder_quantity > 0:
                backorder_fulfillment = min(delivery_today, backorder_quantity)
                backorder_quantity -= backorder_fulfillment
                delivery_today -= backorder_fulfillment
            
            # Add remaining delivery to inventory
            inventory += delivery_today
        else:
            # Lost sales mode: ensure inventory is not negative before adding deliveries
            inventory = max(0, inventory)
            inventory += delivery_today
        
        # Check if we need to reorder (dynamic reorder logic)
        if dynamic_reorder:
            # A. Calculate proper lead time demand with seasonality
            lt_demand = lead_time_demand(i, lead_time)
            
            # B. Calculate safety stock based on method
            if use_service_level_safety:
                safety_stock = calculate_safety_stock_service_level(today_velocity, lead_time)
            else:
                safety_stock = calculate_safety_stock_days(today_velocity)
            
            # Reorder point = lead time demand + safety stock
            reorder_point = lt_demand + safety_stock
            
            # Calculate inventory position (on-hand + on-order)
            on_order = 0
            # Look at ALL future deliveries for proper IP calculation
            for future_day in range(i + 1, days):
                if future_day in delivery_dict:
                    on_order += delivery_dict[future_day]
                if future_day in pending_deliveries:
                    on_order += pending_deliveries[future_day]
            
            # Include backorders in inventory position calculation
            if stockout_mode == 'backorders':
                inventory_position = inventory + on_order - backorder_quantity
            else:
                inventory_position = inventory + on_order
            
            # Check for recent reorders to prevent excessive ordering
            recent_reorder = False
            for check_day in range(max(0, i - min_days_between_orders), i):
                if check_day < len(forecast_data['reorder_trigger']) and forecast_data['reorder_trigger'][check_day]:
                    recent_reorder = True
                    break
            
            # C. Apply reorder policy
            reorder_needed = (inventory_position <= reorder_point and 
                            not recent_reorder and
                            i + lead_time < days)
            
            if reorder_needed:
                if reorder_policy == 'R_S':  # Order-up-to policy
                    # Calculate order-up-to level: LT demand + SS + cycle coverage
                    cycle_demand = get_daily_velocity(current_date) * cycle_cover_days
                    order_up_to_level = lt_demand + safety_stock + cycle_demand
                    
                    # Order quantity to reach order-up-to level
                    order_quantity = order_up_to_level - inventory_position
                    
                elif reorder_policy == 's_Q':  # Fixed lot size
                    # Fixed order quantity (could be EOQ or other fixed amount)
                    order_quantity = max(lt_demand, moq)  # Simple fixed lot = LT demand or MOQ
                    
                elif reorder_policy == 'EOQ':  # Economic Order Quantity
                    # Simplified EOQ calculation (would need setup costs and holding costs)
                    annual_demand = today_velocity * 365
                    # Simplified EOQ = sqrt(2 * D * S / H) - using rough estimates
                    estimated_eoq = math.sqrt(2 * annual_demand * 100 / 0.25)  # Rough estimates
                    order_quantity = max(estimated_eoq, lt_demand)
                
                else:
                    # Default to order-up-to
                    order_quantity = lt_demand + safety_stock - inventory_position
                
                # Round to casepack and ensure MOQ
                order_quantity = round_to_casepack(order_quantity, casepack, moq)
                
                # Ensure minimum reasonable order
                if order_quantity > 0:
                    # Schedule the delivery for lead_time days from now
                    arrival_day = i + lead_time
                    if arrival_day < days:  # Only schedule if within forecast horizon
                        if arrival_day not in pending_deliveries:
                            pending_deliveries[arrival_day] = 0
                        pending_deliveries[arrival_day] += order_quantity
                        
                        # E. Immediately update inventory position to prevent double-trigger
                        inventory_position += order_quantity
                        
                        # Record the reorder event
                        forecast_data['reorder_trigger'][i] = True
                        forecast_data['reorder_amount'][i] = order_quantity
                        forecast_data['reorder_arrival_day'][i] = arrival_day
        
        # F. Handle demand consumption based on stockout mode
        demand_to_fulfill = today_velocity
        lost_sales = 0
        
        if stockout_mode == 'backorders':
            if inventory >= demand_to_fulfill:
                # Can fulfill all demand
                inventory -= demand_to_fulfill
            else:
                # Partial fulfillment, rest becomes backorder
                backorder_addition = demand_to_fulfill - inventory
                backorder_quantity += backorder_addition
                inventory = 0
        else:
            # Lost sales mode
            if inventory >= demand_to_fulfill:
                inventory -= demand_to_fulfill
            else:
                # Lost sales
                lost_sales = demand_to_fulfill - inventory
                inventory = 0
        
        # Calculate fill rate
        if demand_to_fulfill > 0:
            filled_demand = demand_to_fulfill - lost_sales
            fill_rate = filled_demand / demand_to_fulfill
        else:
            fill_rate = 1.0
        
        # Calculate on-order and inventory position for tracking
        on_order_today = 0
        for future_day in range(i + 1, days):
            if future_day in delivery_dict:
                on_order_today += delivery_dict[future_day]
            if future_day in pending_deliveries:
                on_order_today += pending_deliveries[future_day]
        
        # Calculate current safety stock and reorder point for tracking
        if use_service_level_safety:
            current_safety_stock = calculate_safety_stock_service_level(today_velocity, lead_time)
        else:
            current_safety_stock = calculate_safety_stock_days(today_velocity)
        
        current_reorder_point = lead_time_demand(i, lead_time) + current_safety_stock
        
        # Record today's data
        forecast_data['inventory'][i] = inventory
        forecast_data['velocity'][i] = today_velocity
        forecast_data['delivery'][i] = 1 if delivery_today > 0 else 0
        forecast_data['delivery_amount'][i] = delivery_today
        forecast_data['inventory_position'][i] = inventory + on_order_today - (backorder_quantity if stockout_mode == 'backorders' else 0)
        forecast_data['on_order'][i] = on_order_today
        forecast_data['safety_stock'][i] = current_safety_stock
        forecast_data['reorder_point'][i] = current_reorder_point
        forecast_data['lost_sales'][i] = lost_sales
        forecast_data['backorders'][i] = backorder_quantity if stockout_mode == 'backorders' else 0
        forecast_data['fill_rate'][i] = fill_rate
    
    # Convert to DataFrame
    forecast_df = pd.DataFrame(forecast_data)
    
    return forecast_df

def analyze_forecast(forecast_df):
    """
    Analyze the forecast data to provide comprehensive insights.
    
    Parameters:
    -----------
    forecast_df : pandas.DataFrame
        The forecast data with professional inventory metrics
        
    Returns:
    --------
    dict
        Dictionary containing forecast analytics
    """
    analytics = {}
    
    # Check for stockouts
    stockout_days = forecast_df[forecast_df['inventory'] == 0]
    analytics['stockout_count'] = len(stockout_days)
    
    # Calculate consecutive stockout days
    if not stockout_days.empty:
        analytics['first_stockout_day'] = stockout_days.iloc[0]['day']
        analytics['stockout_dates'] = stockout_days['date'].tolist()
        
        # Find consecutive stockout periods
        consecutive_periods = []
        current_period = []
        
        for i, row in stockout_days.iterrows():
            day = row['day']
            if not current_period or day == current_period[-1] + 1:
                current_period.append(day)
            else:
                consecutive_periods.append(current_period)
                current_period = [day]
                
        if current_period:
            consecutive_periods.append(current_period)
            
        # Calculate longest stockout period
        if consecutive_periods:
            longest_period = max(consecutive_periods, key=len)
            analytics['longest_stockout_period'] = len(longest_period)
            analytics['longest_stockout_start'] = min(longest_period)
            analytics['stockout_periods_count'] = len(consecutive_periods)
        else:
            analytics['longest_stockout_period'] = 0
            analytics['longest_stockout_start'] = None
            analytics['stockout_periods_count'] = 0
    else:
        analytics['first_stockout_day'] = None
        analytics['stockout_dates'] = []
        analytics['longest_stockout_period'] = 0
        analytics['longest_stockout_start'] = None
        analytics['stockout_periods_count'] = 0
    
    # Calculate average inventory level
    analytics['avg_inventory'] = forecast_df['inventory'].mean()
    
    # Calculate min/max inventory
    analytics['min_inventory'] = forecast_df['inventory'].min()
    analytics['max_inventory'] = forecast_df['inventory'].max()
    
    # Count reorder events
    analytics['reorder_count'] = forecast_df['reorder_trigger'].sum()
    
    # Calculate total reordered quantity
    analytics['total_reordered'] = forecast_df['reorder_amount'].sum()
    
    # Get delivery events
    deliveries = forecast_df[forecast_df['delivery'] > 0]
    analytics['delivery_count'] = len(deliveries)
    analytics['total_delivered'] = forecast_df['delivery_amount'].sum()
    
    # Calculate service level metrics
    total_demand = forecast_df['velocity'].sum()
    total_lost_sales = forecast_df['lost_sales'].sum()
    
    if total_demand > 0:
        analytics['service_level'] = (total_demand - total_lost_sales) / total_demand
        analytics['fill_rate'] = analytics['service_level']  # Same metric
    else:
        analytics['service_level'] = 1.0
        analytics['fill_rate'] = 1.0
    
    analytics['total_lost_sales'] = total_lost_sales
    analytics['total_demand'] = total_demand
    
    # Backorder analytics (if applicable)
    if 'backorders' in forecast_df.columns:
        analytics['max_backorders'] = forecast_df['backorders'].max()
        analytics['avg_backorders'] = forecast_df['backorders'].mean()
        analytics['total_backorder_days'] = len(forecast_df[forecast_df['backorders'] > 0])
    
    # Inventory position analytics
    analytics['avg_inventory_position'] = forecast_df['inventory_position'].mean()
    analytics['min_inventory_position'] = forecast_df['inventory_position'].min()
    analytics['max_inventory_position'] = forecast_df['inventory_position'].max()
    
    # Safety stock analytics
    if 'safety_stock' in forecast_df.columns:
        analytics['avg_safety_stock'] = forecast_df['safety_stock'].mean()
        # Calculate how often inventory fell below safety stock
        below_safety_stock = forecast_df[forecast_df['inventory'] < forecast_df['safety_stock']]
        analytics['days_below_safety_stock'] = len(below_safety_stock)
        analytics['pct_days_below_safety_stock'] = len(below_safety_stock) / len(forecast_df) * 100
    
    # Reorder point analytics
    if 'reorder_point' in forecast_df.columns:
        analytics['avg_reorder_point'] = forecast_df['reorder_point'].mean()
        # Calculate how often IP fell below ROP
        below_rop = forecast_df[forecast_df['inventory_position'] < forecast_df['reorder_point']]
        analytics['days_below_rop'] = len(below_rop)
        analytics['pct_days_below_rop'] = len(below_rop) / len(forecast_df) * 100
    
    # Calculate turns and cycle metrics
    if analytics['avg_inventory'] > 0:
        analytics['inventory_turns'] = total_demand / analytics['avg_inventory']
        analytics['days_of_supply'] = analytics['avg_inventory'] / (total_demand / len(forecast_df))
    else:
        analytics['inventory_turns'] = 0
        analytics['days_of_supply'] = 0
    
    return analytics

def get_default_seasonality():
    """
    Returns a default seasonality factor dictionary.
    
    Returns:
    --------
    dict
        Dictionary mapping months (1-12) to seasonality factors
    """
    return {
        1: 1.0,   # January
        2: 1.0,   # February
        3: 1.0,   # March
        4: 1.0,   # April
        5: 1.0,   # May
        6: 1.0,   # June
        7: 1.0,   # July
        8: 1.0,   # August
        9: 1.0,   # September
        10: 1.0,  # October
        11: 1.0,  # November
        12: 1.0   # December
    }
