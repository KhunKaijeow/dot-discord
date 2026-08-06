import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import PathPatch
from matplotlib.path import Path
import pandas as pd
import numpy as np

def generate_price_chart(dates, prices, label: str, color_theme: str = "green", currency_symbol: str = "$") -> io.BytesIO:
    """
    Generates a premium, modern, dark-themed price chart for Discord embeds.
    Featuring a glowing price line, fading vertical gradient, and glowing current price dot.
    
    Parameters:
    - dates: Iterable of datetime objects or pandas Timestamps.
    - prices: Iterable of float prices corresponding to the dates.
    - label: Text label for the asset (e.g. 'AAPL', 'BTC/USDT').
    - color_theme: 'green' (up trend), 'red' (down trend), or 'gold' (for gold assets).
    - currency_symbol: Currency symbol to format Y axis values (e.g. '$', '฿').
    
    Returns:
    - io.BytesIO containing the PNG image bytes.
    """
    # Convert inputs to numpy format for easy manipulation
    prices_arr = np.array(prices, dtype=float)
    
    # Check if dates are already datetime objects; if not, convert
    dates_pd = pd.to_datetime(list(dates))
    dates_float = mdates.date2num(dates_pd)

    # Set up colors
    # Discord embed background is #2b2d31. We use this to blend seamlessly.
    bg_color = "#2b2d31"
    grid_color = "#3f4248"
    text_color = "#b5bac1"  # Discord muted gray text
    
    if color_theme == "green":
        line_color = "#2ecc71"  # Neon Green
    elif color_theme == "red":
        line_color = "#e74c3c"  # Neon Red
    elif color_theme == "gold":
        line_color = "#f1c40f"  # Gold Yellow
    else:
        line_color = "#95a5a6"

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(7.5, 3.5), facecolor=bg_color)
    ax.set_facecolor(bg_color)

    # Set limits with padding (5% buffer)
    ymin, ymax = min(prices_arr), max(prices_arr)
    yrange = ymax - ymin if ymax != ymin else 1.0
    y_limit_bottom = ymin - (yrange * 0.05)
    y_limit_top = ymax + (yrange * 0.05)
    
    ax.set_ylim(y_limit_bottom, y_limit_top)
    ax.set_xlim(dates_float[0], dates_float[-1])

    # 1. Gradient Fill Under the Curve
    # Construct polygon coordinates for the area under the curve
    path_coords = np.column_stack([
        np.append(dates_float, [dates_float[-1], dates_float[0]]),
        np.append(prices_arr, [y_limit_bottom, y_limit_bottom])
    ])
    path = Path(path_coords)
    patch = PathPatch(path, facecolor='none', edgecolor='none')
    ax.add_patch(patch)

    # Draw vertical gradient (fades from line_color to bg_color)
    gradient = np.linspace(1, 0, 100).reshape(-1, 1)
    cmap = LinearSegmentedColormap.from_list('custom_gradient', [(0, line_color), (1, bg_color)])
    ax.imshow(
        gradient,
        aspect='auto',
        extent=[dates_float[0], dates_float[-1], y_limit_bottom, y_limit_top],
        cmap=cmap,
        clip_path=patch,
        clip_on=True,
        zorder=1
    )

    # 2. Glowing Line Effect (Layered lines with transparency)
    ax.plot(dates_pd, prices_arr, color=line_color, linewidth=5, alpha=0.15, solid_capstyle='round', zorder=2)
    ax.plot(dates_pd, prices_arr, color=line_color, linewidth=3, alpha=0.35, solid_capstyle='round', zorder=3)
    ax.plot(dates_pd, prices_arr, color=line_color, linewidth=1.8, alpha=1.0, solid_capstyle='round', zorder=4)

    # 3. Glowing Last Price Dot
    ax.scatter(dates_float[-1], prices_arr[-1], color=line_color, s=120, alpha=0.25, zorder=5)
    ax.scatter(dates_float[-1], prices_arr[-1], color=line_color, s=35, zorder=6, edgecolors='#ffffff', linewidths=0.8)

    # Styling grids & ticks
    ax.grid(True, which='both', color=grid_color, linestyle=':', linewidth=0.8, alpha=0.5, zorder=0)
    
    # Hide all borders for clean look
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
