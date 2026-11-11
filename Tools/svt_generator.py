import os
from PyQt6.QtGui import QIcon

class IconFactory:
    # 1. State Matrix Configurations (Colors and Badges)
    STATES = {
        "new": {
            "primary": "#2ecc71",     # Vibrant Green
            "secondary": "#a3e4d7",   
            "opacity": "1.0",
            "badge": '<circle cx="26" cy="26" r="5" fill="#2ecc71" stroke="#ffffff" stroke-width="1.5"/>'
        },
        "active": {
            "primary": "#3498db",     # Vibrant Blue
            "secondary": "#aed6f1",
            "opacity": "1.0",
            "badge": ""               # Clean base icon
        },
        "nonactive": {
            "primary": "#95a5a6",     # Muted Slate Gray
            "secondary": "#d5dbdb",
            "opacity": "0.7",
            "badge": ""
        },
        "disabled": {
            "primary": "#7f8c8d",     # Dark Gray
            "secondary": "#bdc3c7",
            "opacity": "0.4",         # High transparency for visual dimming
            "badge": '<line x1="6" y1="26" x2="26" y2="6" stroke="#e74c3c" stroke-width="3" stroke-linecap="round"/>' # Red strike-through
        }
    }

    # 2. Base Vector Geometry (Canvas is 32x32 pixels)
    SHAPES = {
        "user": '''
            <circle cx="16" cy="11" r="6" fill="{primary}" />
            <path d="M6,26 C6,20 10,18 16,18 C22,18 26,20 26,26" fill="{primary}" />
        ''',
        "forum": '''
            <path d="M6,8 C4.9,8 4,8.9 4,10 L4,20 C4,21.1 4.9,22 6,22 L8,22 L8,25 L12,22 L18,22 C19.1,22 20,21.1 20,20 L20,10 C20,8.9 19.1,8 18,8 Z" fill="{primary}" />
            <path d="M14,12 L24,12 C25.1,12 26,12.9 26,14 L26,21 C26,22.1 25.1,23 24,23 L22,23 L22,26 L18,23 L14,23 Z" fill="{secondary}" opacity="0.8" />
        '''
    }

    @classmethod
    def make_svg(cls, obj_type, state):
        cfg = cls.STATES[state]
        geometry = cls.SHAPES[obj_type].format(primary=cfg["primary"], secondary=cfg["secondary"])
        
        # Assemble standard valid standalone SVG text wrapper
        return f'''<?xml version="1.0" encoding="utf-8"?>
        <svg version="1.1" xmlns="http://w3.org" width="32" height="32" viewBox="0 0 32 32" opacity="{cfg["opacity"]}">
            {geometry}
            {cfg["badge"]}
        </svg>'''

    @classmethod
    def generate_all_assets(cls, output_dir="assets"):
        """Generates all 8 SVG files into an assets folder"""
        os.makedirs(output_dir, exist_ok=True)
        for obj_type in cls.SHAPES.keys():
            for state in cls.STATES.keys():
                filename = f"{obj_type}_{state}.svg"
                filepath = os.path.join(output_dir, filename)
                
                svg_content = cls.make_svg(obj_type, state)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(svg_content)
                print(f"Generated asset: {filepath}")

# If run directly, it will drop the 8 perfect files onto your computer instantly
if __name__ == "__main__":
    IconFactory.generate_all_assets(os.path.relpath('../Resources/images'))
