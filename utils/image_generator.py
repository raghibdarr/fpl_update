import io
from PIL import Image, ImageDraw, ImageFont, ImageColor, ImageFilter
from typing import Dict, List, Any, Optional

# Cup colors (duplicated to avoid changing call signatures or cross-module deps)
CUP_COLORS = {
    "UCL": "#1A3772",
    "UEL": "#F25E27",
    "UECL": "#6CC24A",
    "EFL": "#1D925F",
    "FA": "#D70024"
}


def create_table_image(teams):
    # Define image properties
    width = 1000
    height = 50 + len(teams) * 30
    padding = 10
    font = ImageFont.truetype("arial.ttf", 16)
    header_font = ImageFont.truetype("arialbd.ttf", 16)

    # Create image and drawing context
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)

    # Define column widths
    col_widths = [50, 200, 50, 50, 50, 50, 50, 50, 50, 50]
    
    # Draw headers
    headers = ["Pos", "Team", "Played", "Won", "Drawn", "Lost", "GF", "GA", "GD", "Points"]
    x = padding
    for header, col_width in zip(headers, col_widths):
        draw.text((x, padding), header, font=header_font, fill='black')
        x += col_width

    # Draw team data
    for i, team in enumerate(teams):
        y = 40 + i * 30
        x = padding
        row = [
            str(team['position']),
            team['name'],
            str(team['played']),
            str(team['win']),
            str(team['draw']),
            str(team['loss']),
            str(team.get('goals_for', 'N/A')),
            str(team.get('goals_against', 'N/A')),
            str(team.get('goal_difference', 'N/A')),
            str(team['points'])
        ]
        for text, col_width in zip(row, col_widths):
            draw.text((x, y), text, font=font, fill='black')
            x += col_width

        # Draw alternating row backgrounds
        if i % 2 == 0:
            draw.rectangle([0, y-5, width, y+25], fill='#f0f0f0')

    # Draw horizontal lines
    for i in range(len(teams) + 1):
        y = 35 + i * 30
        draw.line([(0, y), (width, y)], fill='#d0d0d0')

    # Draw vertical lines
    x = 0
    for col_width in col_widths:
        x += col_width
        draw.line([(x, 0), (x, height)], fill='#d0d0d0')

    return image


def get_fixture_color(fixture):
    if not fixture['opponent']:
        return 'lightgrey'
    fdr = fixture['fdr']
    if fdr == 1:
        return '#375523'  # Dark Green
    elif fdr == 2:
        return '#01FC7A'  # Light Green
    elif fdr == 3:
        return '#E7E7E7'  # Grey
    elif fdr == 4:
        return '#FF1751'  # Light Red
    else:
        return '#80072D'  # Dark Red


def get_text_color(fixture):
    if fixture['fdr'] >= 4:
        return 'white'
    return 'black'


def fit_text_to_width(draw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = '…'
    # Binary search for the longest prefix that fits
    lo, hi = 0, len(text)
    best = ''
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid] + ellipsis
        if draw.textlength(candidate, font=font) <= max_width:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best if best else (text[:1] + ellipsis)


def wrap_text_to_two_lines(draw, text: str, font, max_width: int):
    if draw.textlength(text, font=font) <= max_width:
        return text, ''
    tokens = text.split()
    if len(tokens) == 1:
        # No spaces to wrap; fall back to ellipsis on one line
        return fit_text_to_width(draw, tokens[0], font, max_width), ''
    line1_tokens = []
    for token in tokens:
        test = (' '.join(line1_tokens + [token])).strip()
        if draw.textlength(test, font=font) <= max_width:
            line1_tokens.append(token)
        else:
            break
    if not line1_tokens:
        # First token alone doesn't fit; ellipsize single-line
        return fit_text_to_width(draw, tokens[0], font, max_width), ''
    line1 = ' '.join(line1_tokens)
    remaining = ' '.join(tokens[len(line1_tokens):]).strip()
    if not remaining:
        return line1, ''
    line2 = fit_text_to_width(draw, remaining, font, max_width)
    return line1, line2


def create_fixture_grid(fixture_data, num_gameweeks, start_gw, team_names, gw_dates, sort_method, team_positions, team_points, cup_fixture_buckets):
    cell_width, cell_height = 100, 30
    team_column_width = 120
    position_column_width = 40 if sort_method == "table" else 0
    points_column_width = 40 if sort_method == "table" else 0
    spacing = 10
    padding = 20
    header_height_small = 25  # Height for Pos, Club, Pts headers
    header_height_large = 50  # Height for GW headers
    gap_height = 10  # Gap between headers and data
    
    # Calculate total number of columns including cup fixtures
    total_columns = num_gameweeks + sum(1 for gw in range(start_gw, start_gw + num_gameweeks) if gw in cup_fixture_buckets)
    
    width = padding * 2 + position_column_width + team_column_width + points_column_width + spacing + (cell_width * total_columns)
    height = padding * 2 + header_height_large + gap_height + (cell_height * len(fixture_data))
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    font = ImageFont.truetype("arial.ttf", 16)
    bold_font = ImageFont.truetype("arialbd.ttf", 16)
    header_font = ImageFont.truetype("arialbd.ttf", 16)
    date_font = ImageFont.truetype("arial.ttf", 14)
    cup_font = ImageFont.truetype("arial.ttf", 12)  # slightly smaller for CUP cells
    cup_bold_font = ImageFont.truetype("arialbd.ttf", 12)
    
    # Draw headers for position, club, and points columns only if sort_method is "table"
    if sort_method == "table":
        draw.rectangle([padding, padding + header_height_large - header_height_small, padding + position_column_width, padding + header_height_large], outline='black')
        draw.text((padding + position_column_width/2, padding + header_height_large - 5), "Pos", font=header_font, fill='black', anchor="mb")
        
        draw.rectangle([padding + position_column_width + team_column_width, padding + header_height_large - header_height_small, padding + position_column_width + team_column_width + points_column_width, padding + header_height_large], outline='black')
        draw.text((padding + position_column_width + team_column_width + points_column_width/2, padding + header_height_large - 5), "Pts", font=header_font, fill='black', anchor="mb")
    
    # Draw club header
    draw.rectangle([padding + position_column_width, padding + header_height_large - header_height_small, padding + position_column_width + team_column_width, padding + header_height_large], outline='black')
    draw.text((padding + position_column_width + 5, padding + header_height_large - 5), "Club", font=header_font, fill='black', anchor="lb")
    
    # Draw headers and dates for gameweeks and cup fixtures
    column = 0
    for i in range(num_gameweeks):
        gw = start_gw + i
        x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
        draw.rectangle([x, padding, x + cell_width, padding + header_height_large], outline='black')
        draw.text((x + cell_width/2, padding + 10), gw_dates.get(gw, ""), font=date_font, fill='black', anchor="mt")
        draw.text((x + cell_width/2, padding + header_height_large - 10), f"GW{gw}", font=header_font, fill='black', anchor="mb")
        column += 1
        
        if gw in cup_fixture_buckets:
            x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
            draw.rectangle([x, padding, x + cell_width, padding + header_height_large], fill='lightblue', outline='black')
            draw.text((x + cell_width/2, padding + header_height_large/2), "CUP", font=header_font, fill='black', anchor="mm")
            column += 1
    
    # Draw team names, positions, points, and fixtures
    for i, (team_short, fixtures) in enumerate(fixture_data.items()):
        y = padding + header_height_large + gap_height + i*cell_height
        team_full = team_names[team_short]
        
        # Draw position (in bold) only if sort_method is "table"
        if sort_method == "table":
            draw.rectangle([padding, y, padding + position_column_width, y + cell_height], outline='black')
            draw.text((padding + position_column_width/2, y + cell_height/2), str(team_positions.get(team_short, '')), font=bold_font, fill='black', anchor="mm")
        
        # Draw team name (in bold)
        draw.rectangle([padding + position_column_width, y, padding + position_column_width + team_column_width, y + cell_height], outline='black')
        draw.text((padding + position_column_width + 5, y + cell_height/2), team_full, font=bold_font, fill='black', anchor="lm")
        
        # Draw points (in bold) only if sort_method is "table"
        if sort_method == "table":
            draw.rectangle([padding + position_column_width + team_column_width, y, padding + position_column_width + team_column_width + points_column_width, y + cell_height], outline='black')
            draw.text((padding + position_column_width + team_column_width + points_column_width/2, y + cell_height/2), str(team_points.get(team_short, '')), font=bold_font, fill='black', anchor="mm")
        
        column = 0
        for j in range(num_gameweeks):
            gw = start_gw + j
            x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
            
            # Draw league fixture
            if j < len(fixtures):
                fixture = fixtures[j]
                color = get_fixture_color(fixture)
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill=color, outline='black')
                
                is_home = fixture['opponent'].isupper()
                text_font = bold_font if is_home else font
                
                draw.text((x + cell_width/2, y + cell_height/2), fixture['opponent'], font=text_font, fill='black', anchor="mm")
            else:
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill='white', outline='black')
            
            column += 1
            
            # Draw cup fixture if exists
            if gw in cup_fixture_buckets:
                x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
                
                cup_fixture = next((f for f in cup_fixture_buckets[gw] if f['team'] == team_short), None)
                if cup_fixture:
                    cup_color = CUP_COLORS.get(cup_fixture['competition'], 'lightblue')  # Default to lightblue if competition not found
                    draw.rectangle([x, y, x + cell_width, y + cell_height], fill=cup_color, outline='black')
                    
                    # Use full opponent name if available; otherwise use existing opponent text
                    opponent_key = cup_fixture.get('opponent_full') or cup_fixture['opponent']
                    display_text = opponent_key
                    text_font = cup_bold_font if cup_fixture['is_home'] else cup_font
                    
                    # Determine text color based on background color brightness
                    bg_color = ImageColor.getrgb(cup_color)
                    brightness = (bg_color[0] * 299 + bg_color[1] * 587 + bg_color[2] * 114) / 1000
                    text_color = 'black' if brightness > 128 else 'white'
                    
                    # Wrap into up to two lines within the cell
                    max_text_width = cell_width - 8
                    line1, line2 = wrap_text_to_two_lines(draw, display_text, text_font, max_text_width)
                    if line2:
                        ascent, descent = text_font.getmetrics()
                        line_height = ascent + descent
                        gap_px = max(1, int(line_height * 0.15))
                        total_h = line_height * 2 + gap_px
                        top_y = y + (cell_height - total_h) / 2
                        y1 = top_y + line_height / 2
                        y2 = y1 + line_height + gap_px
                        draw.text((x + cell_width/2, y1), line1, font=text_font, fill=text_color, anchor="mm")
                        draw.text((x + cell_width/2, y2), line2, font=text_font, fill=text_color, anchor="mm")
                    else:
                        fitted = fit_text_to_width(draw, line1, text_font, max_text_width)
                        draw.text((x + cell_width/2, y + cell_height/2), fitted, font=text_font, fill=text_color, anchor="mm")
                else:
                    draw.rectangle([x, y, x + cell_width, y + cell_height], fill='lightblue', outline='black')
                
                column += 1
    
    # Draw gridlines for fixture columns only
    for i in range(total_columns + 1):
        x = padding + position_column_width + team_column_width + points_column_width + spacing + i*cell_width
        draw.line([(x, padding + header_height_large + gap_height), (x, height - padding)], fill='black', width=1)
    
    # Draw horizontal gridlines for team rows only, starting below the first team
    for i in range(1, len(fixture_data) + 1):
        y = padding + header_height_large + gap_height + i*cell_height
        draw.line([(padding, y), (padding + position_column_width + team_column_width + points_column_width, y)], fill='black', width=1)
        draw.line([(padding + position_column_width + team_column_width + points_column_width + spacing, y), (width - padding, y)], fill='black', width=1)
    
    # Draw vertical lines for position and points columns, but not connecting to the header boxes
    draw.line([(padding + position_column_width, padding + header_height_large + gap_height), (padding + position_column_width, height - padding)], fill='black', width=1)
    draw.line([(padding + position_column_width + team_column_width, padding + header_height_large + gap_height), (padding + position_column_width + team_column_width, height - padding)], fill='black', width=1)
    
    return image


def create_leaderboard_image(standings):
    width, height = 1300, 70 + len(standings) * 60
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    font_regular = ImageFont.load_default().font_variant(size=24)
    font_bold = ImageFont.load_default().font_variant(size=24)
    font_header = ImageFont.load_default().font_variant(size=28)
    
    # Define column widths
    rank_width = 90
    team_width = 450
    gw_width = 90
    tot_width = 90
    value_width = 100
    or_width = 100
    
    # Define column widths and positions
    rank_center = rank_width // 2
    team_start = rank_width + 20
    gw_center = width - or_width - value_width - tot_width - gw_width // 2
    tot_center = width - or_width - value_width - tot_width // 2
    value_center = width - or_width - value_width // 2
    or_center = width - or_width // 2
    
    # Adjust header vertical position
    header_y = 40  # Moved down from 20
    
    # Draw headers
    draw.text((rank_center, header_y), "Rank", font=font_header, fill='black', anchor="mm")
    draw.text((team_start, header_y), "Team & Manager", font=font_header, fill='black', anchor="lm")
    draw.text((gw_center, header_y), "GW", font=font_header, fill='black', anchor="mm")
    draw.text((tot_center, header_y), "TOT", font=font_header, fill='black', anchor="mm")
    draw.text((value_center, header_y), "Value", font=font_header, fill='black', anchor="mm")
    draw.text((or_center, header_y), "OR", font=font_header, fill='black', anchor="mm")
    
    # Draw header underline (moved closer to headers)
    draw.line([(0, header_y + 25), (width, header_y + 25)], fill='black', width=2)
    
    def draw_slightly_bold_text(x, y, text, font, fill='black'):
        # Draw the text twice with a slight offset for a slightly bolder effect
        draw.text((x, y), text, font=font, fill=fill, anchor="lm")
        draw.text((x+1, y), text, font=font, fill=fill, anchor="lm")
    
    # Adjust the starting y-coordinate for the standings
    standings_start_y = header_y + 35
    
    # Draw standings
    for i, entry in enumerate(standings):
        y = standings_start_y + i * 60
        row_center = y + 30
        
        # Calculate positions for rank and indicator
        rank_text_width = draw.textlength(str(entry['rank']), font=font_regular)
        indicator_width = 20
        total_width = rank_text_width + indicator_width + 5  # 5 px spacing
        start_x = rank_center - total_width // 2
        
        # Draw rank
        draw.text((start_x, row_center), str(entry['rank']), font=font_regular, fill='black', anchor="lm")
        
        # Draw arrow or indicator
        indicator_x = start_x + rank_text_width + 5
        indicator_y = row_center
        if entry['rank'] < entry['last_rank']:
            draw.polygon([(indicator_x, indicator_y + 6), (indicator_x + 10, indicator_y - 6), (indicator_x + 20, indicator_y + 6)], fill='green')
        elif entry['rank'] > entry['last_rank']:
            draw.polygon([(indicator_x, indicator_y - 6), (indicator_x + 10, indicator_y + 6), (indicator_x + 20, indicator_y - 6)], fill='red')
        else:
            draw.rectangle([(indicator_x, indicator_y - 4), (indicator_x + 20, indicator_y + 4)], fill='grey')
        
        # Draw team name (slightly bold) and manager name (regular)
        draw_slightly_bold_text(team_start, row_center - 12, entry.get('entry_name', 'Unknown'), font_bold)
        draw.text((team_start, row_center + 12), entry.get('player_name', 'Unknown'), font=font_regular, fill='black', anchor="lm")
        
        # Draw GW and TOT scores
        draw.text((gw_center, row_center), str(entry.get('event_total', 'N/A')), font=font_regular, fill='black', anchor="mm")
        draw.text((tot_center, row_center), str(entry.get('total', 'N/A')), font=font_regular, fill='black', anchor="mm")
        
        # Draw Team Value
        team_value = entry.get('value', 0) / 10  # Assuming value is in tenths of millions
        draw.text((value_center, row_center), f"{team_value:.1f}m", font=font_regular, fill='black', anchor="mm")
        
        # Draw Overall Rank
        overall_rank = entry.get('overall_rank', 'N/A')
        if isinstance(overall_rank, int):
            if overall_rank >= 1000000:
                overall_rank_text = f"{overall_rank/1000000:.1f}M"
            elif overall_rank >= 1000:
                overall_rank_text = f"{overall_rank/1000:.1f}K"
            else:
                overall_rank_text = f"{overall_rank}"
        else:
            overall_rank_text = str(overall_rank)
        draw.text((or_center, row_center), overall_rank_text, font=font_regular, fill='black', anchor="mm")
        
        # Draw row separator
        draw.line([(0, y + 59), (width, y + 59)], fill='lightgray', width=1)
    
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr


def _safe_font(name: str, size: int):
    try:
        return ImageFont.truetype(name, size)
    except Exception:
        return ImageFont.load_default()


def _centered(draw: ImageDraw.ImageDraw, text: str, font, cx: int, y: int, fill: str):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2, y), text, font=font, fill=fill)


def _row_x_positions(width: int, count: int, margin: int = 80) -> List[int]:
    if count <= 0:
        return []
    step = (width - margin * 2) // (count + 1)
    return [margin + step * (i + 1) for i in range(count)]


def _crop_transparent_borders(image: Image.Image) -> Image.Image:
    """Crop fully transparent padding to allow scaling shirts bigger without excess margins."""
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    alpha = image.split()[3]
    bbox = alpha.getbbox()
    if bbox:
        return image.crop(bbox)
    return image


def _composite_one_sided_rounded_rect(bg: Image.Image, x1: int, y1: int, x2: int, y2: int, *, round_top: bool, radius: int, fill: tuple | str):
    """Composite a rectangle onto bg with only top or bottom corners rounded.
    If round_top=True, top corners rounded and bottom flat; otherwise bottom rounded and top flat.
    """
    w, h = max(0, x2 - x1), max(0, y2 - y1)
    if w <= 0 or h <= 0:
        return
    r = max(0, min(radius, (min(w, h) - 1) // 2))
    mask = Image.new('L', (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    if round_top:
        if r > 0:
            md.rectangle([0, h - r, w, h], fill=255)
    else:
        if r > 0:
            md.rectangle([0, 0, w, r], fill=255)
    color = Image.new('RGBA', (w, h), fill)
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    layer = Image.composite(color, layer, mask)
    bg.alpha_composite(layer, (x1, y1))


def create_squad_image(
    *,
    team_name: str,
    event_name: str,
    total_points: int,
    lines: Dict[str, List[Dict[str, Any]]],
    bench: List[Dict[str, Any]],
    elements_by_id: Dict[int, Dict[str, Any]],
    teams_by_id: Dict[int, Dict[str, Any]],
    live_points: Dict[int, int],
    captain_id: Optional[int],
    vice_id: Optional[int],
    shirts_by_team_code: Dict[int, Image.Image],
    active_chip: Optional[str] = None,
    pitch_image: Optional[Image.Image] = None,
) -> Image.Image:
    # Canvas and colors approx. to FPL app theme
    W, H = 880, 1460
    bg = Image.new('RGBA', (W, H), '#190028')
    draw = ImageDraw.Draw(bg)

    # Fonts
    title_font = _safe_font('arialbd.ttf', 42)
    sub_font = _safe_font('arial.ttf', 26)
    name_font = _safe_font('arialbd.ttf', 20)
    pts_font = _safe_font('arialbd.ttf', 20)
    subs_title_font = _safe_font('arialbd.ttf', 42)

    # Header
    header_h = 180
    draw.rectangle([0, 0, W, header_h], fill='#26093f')
    draw.text((28, 26), team_name, font=title_font, fill='white')
    draw.text((28, 86), event_name, font=sub_font, fill='#c0b6d2')

    # Total points tile
    tile_w, tile_h = 220, 120
    tx, ty = W - tile_w - 28, 30
    draw.rounded_rectangle([tx, ty, tx + tile_w, ty + tile_h], radius=18, fill='#35b6ff')
    _centered(draw, str(total_points), _safe_font('arialbd.ttf', 48), tx + tile_w // 2, ty + 24, 'white')
    _centered(draw, 'Total Points', sub_font, tx + tile_w // 2, ty + 74, 'white')

    # Pitch background (top rounded, bottom flat)
    pitch_y0 = header_h + 10
    pitch_y1 = H - 248
    pitch_rect = [28, pitch_y0, W - 28, pitch_y1]
    draw.rounded_rectangle(pitch_rect, radius=24, fill='#0b6a34')
    # flatten the bottom corners by overdrawing a rectangle strip
    draw.rectangle([pitch_rect[0], pitch_rect[3] - 24, pitch_rect[2], pitch_rect[3]], fill='#0b6a34')
    # If a pitch image was provided, paste it scaled to fit
    if pitch_image is not None:
        pr_w = pitch_rect[2] - pitch_rect[0]
        pr_h = pitch_rect[3] - pitch_rect[1]
        
        # Resize to fill the pitch area (Cover effect)
        img_w, img_h = pitch_image.size
        target_aspect = pr_w / pr_h
        image_aspect = img_w / img_h

        if image_aspect > target_aspect:
            # Image is wider than target, resize by height, crop sides
            new_h = pr_h
            new_w = int(image_aspect * new_h)
            x_offset = (new_w - pr_w) // 2
            y_offset = 0
            scaled = pitch_image.resize((new_w, new_h), Image.LANCZOS)
            scaled = scaled.crop((x_offset, y_offset, x_offset + pr_w, y_offset + pr_h))
        else:
            # Image is taller than target, resize by width, crop top/bottom
            new_w = pr_w
            new_h = int(new_w / image_aspect)
            x_offset = 0
            y_offset = (new_h - pr_h) // 2
            scaled = pitch_image.resize((new_w, new_h), Image.LANCZOS)
            scaled = scaled.crop((x_offset, y_offset, x_offset + pr_w, y_offset + pr_h))

        # Mask: top rounded, bottom flat
        mask = Image.new('L', (pr_w, pr_h), 0)
        mdm = ImageDraw.Draw(mask)
        mdm.rounded_rectangle([0, 0, pr_w, pr_h], radius=24, fill=255)
        mdm.rectangle([0, pr_h - 24, pr_w, pr_h], fill=255)
        bg.paste(scaled.convert('RGBA'), (pitch_rect[0], pitch_rect[1]), mask)

    # Row Y positions
    gk_y = pitch_y0 + 126
    def_y = gk_y + 222
    mid_y = def_y + 222
    fwd_y = mid_y + 222
    bench_y = pitch_y1 + 22
    bench_xs = None  # will be set later if inner container is drawn

    # Card layout constants (fixed pixels; tune as desired)
    CARD_W = 129
    CARD_H = 180
    TOP_GAP = 10        # space above kit
    NAME_H = 29         # player name bar height
    PTS_H = 29          # points bar height
    KIT_MAX_W = CARD_W - 14
    KIT_H = 160

    def draw_player(cx: int, cy: int, pick: Dict[str, Any], bench_mode: bool):
        el = elements_by_id[pick['element']]
        team = teams_by_id[el['team']]
        team_code = team['code']
        shirt = shirts_by_team_code.get(team_code)

        # Fixed card size/position (centered on cx, cy)
        card_w = CARD_W
        card_h = CARD_H
        card_x = cx - card_w // 2
        card_y = cy - card_h // 2

        # Shadow layer
        # shadow = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
        # sd = ImageDraw.Draw(shadow)
        # sd.rounded_rectangle([0, 0, card_w, card_h], radius=20, fill=(0, 0, 0, 120))
        # shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        # bg.alpha_composite(shadow, (card_x, card_y + 6))
        
        # Glass rectangle (rounded fill to avoid square corners)
        glass = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glass)
        gd.rounded_rectangle(
            [0, 0, card_w - 1, card_h - 1],
            radius=20,
            fill=(255, 255, 255, 48),
            outline=(255, 255, 255, 90),
            width=2,
        )
        bg.alpha_composite(glass, (card_x, card_y))

        # Fixed bars placement
        pts_y = card_y + card_h - PTS_H
        name_y = pts_y - NAME_H

        # Shirt sizing: fixed target height with max width, keeping aspect ratio
        if shirt:
            s = _crop_transparent_borders(shirt).copy()
            # scale primarily to fixed height
            scale_h = KIT_H / s.height
            tw = int(s.width * scale_h)
            th = KIT_H
            # if too wide, cap to max width and scale height accordingly
            if tw > KIT_MAX_W:
                scale_w = KIT_MAX_W / s.width
                tw = KIT_MAX_W
                th = int(s.height * scale_w)
            s = s.resize((tw, th), Image.LANCZOS)

            sx = card_x + (card_w - tw) // 2
            sy = card_y + TOP_GAP
            bg.alpha_composite(s, (sx, sy))

        # Helper to paste a rectangle with only-top or only-bottom rounded corners
        def _paste_one_sided_rounded_rect(x1: int, y1: int, x2: int, y2: int, *, round_top: bool, radius: int, fill: tuple | str):
            w, h = max(0, x2 - x1), max(0, y2 - y1)
            if w <= 0 or h <= 0:
                return
            r = max(0, min(radius, (min(w, h) - 1) // 2))
            # Build mask with desired corners
            mask = Image.new('L', (w, h), 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
            if round_top:
                # flatten bottom corners
                if r > 0:
                    md.rectangle([0, h - r, w, h], fill=255)
            else:
                # flatten top corners
                if r > 0:
                    md.rectangle([0, 0, w, r], fill=255)
            color = Image.new('RGBA', (w, h), fill)
            layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            layer = Image.composite(color, layer, mask)
            bg.alpha_composite(layer, (x1, y1))

        # Name bar (rounded top corners, theme purple text) over the kit
        name = el['web_name']
        theme_purple = '#37003C'
        # shrink width and height by 5px each
        name_x1 = card_x + 2
        name_x2 = card_x + card_w - 3
        name_h = max(1, NAME_H)
        _paste_one_sided_rounded_rect(name_x1, name_y, name_x2, name_y + name_h, round_top=True, radius=5, fill=(255, 255, 255, 255))
        max_name_w = name_x2 - name_x1 - 12
        fitted = fit_text_to_width(draw, name, name_font, max_name_w)
        # center text both horizontally and vertically in the name bar
        name_cx = (name_x1 + name_x2) // 2
        name_cy = name_y + name_h // 2
        draw.text((name_cx, name_cy), fitted, font=name_font, fill=theme_purple, anchor="mm")

        # Points bar (rounded bottom corners) over the kit
        raw_pts = live_points.get(el['id'], 0)
        shown_pts = raw_pts if bench_mode else raw_pts * max(1, pick.get('multiplier', 0))
        pts_x1 = card_x + 2
        pts_x2 = card_x + card_w - 3
        pts_h = max(1, PTS_H)
        _paste_one_sided_rounded_rect(pts_x1, pts_y, pts_x2, pts_y + pts_h, round_top=False, radius=20, fill=ImageColor.getrgb('#37003c') + (255,))
        pts_text = str(shown_pts)
        # center text both horizontally and vertically in the points bar
        pts_cx = (pts_x1 + pts_x2) // 2
        pts_cy = pts_y + pts_h // 2
        draw.text((pts_cx, pts_cy), pts_text, font=pts_font, fill='white', anchor="mm")

        # C / V badge
        if el['id'] == captain_id or el['id'] == vice_id:
            badge = 'C' if el['id'] == captain_id else 'V'
            bx = card_x + card_w - 24
            by = card_y + 24
            r = 16
            draw.ellipse([bx - r, by - r, bx + r, by + r], fill='#ffd000')
            _centered(draw, badge, _safe_font('arialbd.ttf', 18), bx, by - 11, 'black')

    # Draw XI rows with enforced minimum spacing like the subs
    def _centers_with_min_gap(container_x1: int, container_w: int, count: int, *, card_w: int = CARD_W, min_gap: int = 30, padding: int = 40) -> List[int]:
        n = max(1, count)
        usable_w = max(0, container_w - padding * 2)
        required_w = n * card_w + (n - 1) * min_gap
        if required_w <= usable_w:
            left = container_x1 + (container_w - required_w) // 2
            return [int(left + card_w // 2 + i * (card_w + min_gap)) for i in range(n)]
        if n == 1:
            return [container_x1 + container_w // 2]
        step = max(card_w, usable_w // max(1, (n - 1)))
        first_cx = container_x1 + padding
        return [int(first_cx + i * step) for i in range(n)]

    for row_key, y in (('GK', gk_y), ('DEF', def_y), ('MID', mid_y), ('FWD', fwd_y)):
        picks = lines.get(row_key, [])
        cont_x1 = pitch_rect[0]
        cont_w = pitch_rect[2] - pitch_rect[0]
        xs = _centers_with_min_gap(cont_x1, cont_w, len(picks))
        for cx, p in zip(xs, picks):
            draw_player(cx, y, p, bench_mode=False)

    # Substitutes container: flat top, rounded bottom, solid color, connected to pitch
    panel_x1, panel_y1 = 28, pitch_y1
    panel_x2, panel_y2 = W - 28, H - 20
    panel_w, panel_h = panel_x2 - panel_x1, panel_y2 - panel_y1
    if panel_w > 0 and panel_h > 0:
        # Solid color panel (#28002B), bottom rounded only. Avoid stroke at top to keep flat edge.
        _composite_one_sided_rounded_rect(bg, panel_x1, panel_y1, panel_x2, panel_y2, round_top=False, radius=24, fill=ImageColor.getrgb('#28002B'))
        # draw.rounded_rectangle([panel_x1, panel_y1, panel_x2, panel_y2], radius=24, outline=(255, 255, 255, 50))

        # Substitutes title near bottom
        draw.text(((panel_x1 + panel_x2) // 2, panel_y2 - 50), 'Substitutes', font=subs_title_font, fill='white', anchor="mm")

        # Inner glass container sized to the bench row
        n = max(1, len(bench))
        est_card_w = CARD_W
        gap = 60
        inner_w = min(panel_w - 80, est_card_w * n + gap * (n - 1) + 20)
        # add vertical padding so cards don't overflow
        inner_h = CARD_H + 30 
        inner_x1 = panel_x1 + (panel_w - inner_w) // 2
        # overlap upwards onto the pitch
        overlap = 90  # increase/decrease to move further onto pitch
        inner_y1 = panel_y1 - overlap
        inner_x2 = inner_x1 + inner_w
        inner_y2 = inner_y1 + inner_h

        # Glass effect
        # Use pitch portion for blur if overlapping above panel
        crop_y1 = max(inner_y1, pitch_rect[1])
        region = bg.crop((inner_x1, crop_y1, inner_x2, inner_y2)).resize((inner_w, inner_h)).filter(ImageFilter.GaussianBlur(10)).convert('RGBA')
        tint = Image.new('RGBA', (inner_w, inner_h), (255, 255, 255, 40))
        glass = Image.alpha_composite(region, tint)
        mask = Image.new('L', (inner_w, inner_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, inner_w - 1, inner_h - 1], radius=20, fill=255)
        bg.paste(glass, (inner_x1, inner_y1), mask)
        # no outline on the inner glass container (fully transparent border)
        # draw.rounded_rectangle([inner_x1, inner_y1, inner_x2, inner_y2], radius=20, outline=(0, 0, 0, 0))

        # Bench row centered over inner container
        bench_y = inner_y1 + inner_h // 2 + 10
        # Center bench horizontally within inner container with guaranteed gaps
        desired_gap = 30
        n_cards = max(1, len(bench))
        required_w = n_cards * CARD_W + (n_cards - 1) * desired_gap
        usable_w = inner_w - 40  # small side padding inside the glass
        if required_w <= usable_w:
            left = inner_x1 + (inner_w - required_w) // 2
            # convert to centers
            bench_xs = [int(left + CARD_W // 2 + i * (CARD_W + desired_gap)) for i in range(n_cards)]
        else:
            # fallback to proportional spacing without overlap where possible
            margin = max(20, CARD_W // 2)
            step = max(CARD_W, (inner_w - margin * 2) // max(1, (n_cards - 1)))
            first_cx = inner_x1 + margin
            bench_xs = [int(first_cx + i * step) for i in range(n_cards)]

    # Draw bench
    xs = bench_xs if bench_xs else _row_x_positions(W, len(bench))
    for cx, p in zip(xs, bench):
        draw_player(cx, bench_y, p, bench_mode=True)

    # Active chip indicator
    if active_chip:
        chip_text = active_chip.replace('_', ' ').title()
        draw.rounded_rectangle([28, header_h - 38, 28 + 220, header_h - 8], radius=12, fill='#6a2bbd')
        _centered(draw, chip_text, _safe_font('arialbd.ttf', 20), 28 + 110, header_h - 34, 'white')

    return bg