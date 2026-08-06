import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

def generate_price_chart(dates, prices, label: str, color_theme: str = "green", currency_symbol: str = "$") -> io.BytesIO:
    """
    Generates a clean, modern, dark-themed price chart for Discord embeds.
    
    Parameters:
    - dates: Iterable of datetime objects or pandas Timestamps.
    - prices: Iterable of float prices corresponding to the dates.
    - label: Text label for the asset (e.g. 'AAPL', 'BTC/USDT').
    - color_theme: 'green' (up trend), 'red' (down trend), or 'gold' (for gold assets).
    - currency_symbol: Currency symbol to format Y axis values (e.g. '$', '฿').
    
    Returns:
    - io.BytesIO containing the PNG image bytes.
    """
    # Convert inputs to pandas/numpy format for easy manipulation
    prices_arr = np.array(prices, dtype=float)
    
    # Check if dates are already datetime objects; if not, convert
    dates_pd = pd.to_datetime(list(dates))

    # Set up colors
    # Discord embed background is #2b2d31. We use this to blend seamlessly.
    bg_color = "#2b2d31"
    grid_color = "#3f4248"
    text_color = "#dbdee1"  # Discord light gray text
    
    if color_theme == "green":
        line_color = "#2ecc71"
    elif color_theme == "red":
        line_color = "#e74c3c"
    elif color_theme == "gold":
        line_color = "#f1c40f"
    else:
        line_color = "#95a5a6"

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(7.5, 3.5), facecolor=bg_color)
    ax.set_facecolor(bg_color)

    # Plot the line (smooth and clean)
    ax.plot(dates_pd, prices_arr, color=line_color, linewidth=2.5, label=label)

    # Fill area under curve with soft transparency
    # We fill down to the minimum price minus a small buffer (e.g., 2% of the range)
    # or just fill down to the bottom limit of the y-axis
    ymin, ymax = min(prices_arr), max(prices_arr)
    yrange = ymax - ymin if ymax != ymin else 1.0
    y_limit_bottom = ymin - (yrange * 0.05)
    y_limit_top = ymax + (yrange * 0.05)
    
    ax.set_ylim(y_limit_bottom, y_limit_top)
    ax.fill_between(dates_pd, prices_arr, y_limit_bottom, color=line_color, alpha=0.12)

    # Styling grids & ticks
    ax.grid(True, which='both', color=grid_color, linestyle=':', linewidth=0.8, alpha=0.6)
    
    # Hide all spines (borders) for a clean modern look
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Set text colors and sizes
    ax.tick_params(colors=text_color, labelsize=9)
    
    # Format X axis (Dates)
    ax.xaxis.set_major_locator(plt.MaxNLocator(5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))

    # Format Y axis (Prices)
    def y_formatter(x, pos):
        if x >= 1_000_000:
            return f"{currency_symbol}{x/1_000_000:.1f}M"
        elif x >= 1_000:
            return f"{currency_symbol}{x:,.0f}"
        elif x >= 1.0:
            return f"{currency_symbol}{x:,.2f}"
        elif x > 0:
            return f"{currency_symbol}{x:,.4f}"
        return f"{currency_symbol}{x}"

    ax.yaxis.set_major_formatter(plt.FuncFormatter(y_formatter))
    ax.yaxis.set_major_locator(plt.MaxNLocator(5))

    # Padding
    plt.tight_layout()

    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=bg_color, edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    return buf
