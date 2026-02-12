import flet as ft

# -- Color Palette --
COLORS = {
    "background_top": "#357EC7", # Windows Blue
    "background_bottom": "#1A4E85", # Deep Ocean
    "pcp_red": "#c62127",
    "pcp_red_dark": "#4a0b0d",
    "glass_bg": "#40000000", # 25% Black tint
    "glass_border": "#30ffffff",
    "text_white": "white",
    "text_dim": "white70",
    "text_dark": "white30"
}

# -- Styles --
GLASS_STYLE = {
    "bgcolor": COLORS["glass_bg"],
    "border": ft.border.all(1, COLORS["glass_border"]),
    "border_radius": 20,
    "padding": 20,
    "blur": ft.Blur(20, 20, ft.BlurTileMode.MIRROR),
    "animate": ft.Animation(400, "easeOutCubic"),
}

def get_main_gradient():
    """Returns the standard LinearGradient for the app background."""
    return ft.LinearGradient(
        begin=ft.Alignment(0, -1),  # top_center in Flet 0.80
        end=ft.Alignment(0, 1),  # bottom_center in Flet 0.80
        colors=[COLORS["background_top"], COLORS["background_bottom"]],
    )

class FrostOverlay(ft.Container):
    """
    The reusable 'Frost' layer that sits on top of content.
    Must be placed in a Stack over the content it blurs.
    """
    def __init__(self):
        super().__init__(
            expand=True,
            bgcolor="transparent",
            blur=ft.Blur(0, 0, ft.BlurTileMode.CLAMP),
            border_radius=20,
            opacity=1.0,
            animate=ft.Animation(750, "easeOut"), # Defrost duration
            ignore_interactions=True
        )
    
    def freeze(self):
        self.blur = ft.Blur(5, 5, ft.BlurTileMode.CLAMP)
        self.update()
        
    def defrost(self):
        self.blur = ft.Blur(0, 0, ft.BlurTileMode.CLAMP)
        self.update()

class NexusButton(ft.Container):
    """(Planned) Standard Glass Button"""
    pass
