class ColorUtils:

    @staticmethod
    def rgb_tuple_to_hex(rgb: tuple[int, int, int], uppercase: bool = False) -> str:
        r, g, b = rgb
        fmt = "02X" if uppercase else "02x"
        return f"#{r:{fmt}}{g:{fmt}}{b:{fmt}}"

    @staticmethod
    def rgb_list_to_hex(rgb: list, uppercase: bool = False) -> str:
        fmt = "02X" if uppercase else "02x"
        return f"#{rgb[0]:{fmt}}{rgb[1]:{fmt}}{rgb[2]:{fmt}}"

    @staticmethod
    def hex_to_rgb_tuple(hex_color: str) -> tuple[int, int, int]:
        cleaned = hex_color.lstrip("#")
        if len(cleaned) == 3:
            cleaned = "".join(c * 2 for c in cleaned)
        return (
            int(cleaned[0:2], 16),
            int(cleaned[2:4], 16),
            int(cleaned[4:6], 16),
        )

    @staticmethod
    def hex_to_rgb_list(hex_color: str) -> list:
        return list(ColorUtils.hex_to_rgb_tuple(hex_color))