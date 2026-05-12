import pandas as pd
import numpy as np

def calculate_daily_velocity(sales, days):
    """
    Calculate the daily sales velocity for a time period.
    
    Parameters:
    -----------
    sales : float
        Total sales for the time period
    days : int
        Number of days in the time period
    
    Returns:
    --------
    float
        Daily velocity (sales/day)
    """
    if days <= 0:
        return 0
    return sales / days

def calculate_weighted_velocity(velocities, weights):
    """
    Calculate weighted average velocity from individual velocities and weights.
    
    Parameters:
    -----------
    velocities : dict
        Dictionary mapping time periods to their daily velocities
    weights : dict
        Dictionary mapping time periods to their weights
    
    Returns:
    --------
    float
        Weighted average velocity
    """
    weighted_velocity = 0
    weight_sum = sum(weights.values())
    
    # Normalize weights if they don't sum to 1
    if weight_sum != 1.0 and weight_sum > 0:
        normalized_weights = {period: weight/weight_sum for period, weight in weights.items()}
    else:
        normalized_weights = weights
    
    # Calculate weighted average
    for period, velocity in velocities.items():
        if period in normalized_weights:
            weighted_velocity += velocity * normalized_weights[period]
    
    return weighted_velocity

def get_default_periods():
    """
    Returns default time periods for weighted velocity calculation.
    
    Returns:
    --------
    list
        List of default time periods
    """
    return ["7_day", "14_day", "30_day", "60_day", "90_day"]

def get_period_days(period):
    """
    Get the number of days for a given period identifier.
    
    Parameters:
    -----------
    period : str
        Period identifier (e.g., "7_day", "30_day")
    
    Returns:
    --------
    int
        Number of days in the period
    """
    try:
        days = int(period.split('_')[0])
        return days
    except:
        # Default fallback
        return 0

def format_period_name(period):
    """
    Format period identifier for display.
    
    Parameters:
    -----------
    period : str
        Period identifier (e.g., "7_day", "30_day")
    
    Returns:
    --------
    str
        Formatted period name
    """
    try:
        days = int(period.split('_')[0])
        return f"{days}-day"
    except:
        return period

def get_period_data_table(sales_data, weights):
    """
    Generate a table with period data for display.
    
    Parameters:
    -----------
    sales_data : dict
        Dictionary mapping periods to sales values
    weights : dict
        Dictionary mapping periods to weights
    
    Returns:
    --------
    pandas.DataFrame
        DataFrame containing period data
    """
    data = []
    
    for period, sales in sales_data.items():
        days = get_period_days(period)
        velocity = calculate_daily_velocity(sales, days) if days > 0 else 0
        weight = weights.get(period, 0)
        
        data.append({
            'Period': format_period_name(period),
            'Sales': sales,
            'Days': days,
            'Daily Velocity': velocity,
            'Weight': weight,
            'Weighted Velocity': velocity * weight
        })
    
    return pd.DataFrame(data)