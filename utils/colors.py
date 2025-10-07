def get_fdr_color(difficulty):
    if difficulty == 1:
        return 0x375523  # Dark Green
    elif difficulty == 2:
        return 0x01FC7A  # Light Green
    elif difficulty == 3:
        return 0xE7E7E7  # Grey
    elif difficulty == 4:
        return 0xFF1751  # Light Red
    else:
        return 0x80072D  # Dark Red


