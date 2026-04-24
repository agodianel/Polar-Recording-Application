"""Dark theme and styling for PolarRecorder.

Premium dark theme inspired by medical/research monitoring systems.
Uses a deep navy-black base with teal/cyan accents.
"""

# ─── Color Palette ──────────────────────────────────────────────────────────────
COLORS = {
    # Base
    "bg_primary": "#0a0e17",      # Deep navy-black
    "bg_secondary": "#111827",     # Slightly lighter panel
    "bg_tertiary": "#1a2332",      # Card/widget background
    "bg_hover": "#1f2d42",         # Hover states
    "bg_input": "#0d1424",         # Input field background

    # Borders
    "border": "#1e293b",           # Subtle border
    "border_active": "#22d3ee",    # Active/focused border

    # Text
    "text_primary": "#e2e8f0",     # Primary text
    "text_secondary": "#94a3b8",   # Secondary text
    "text_muted": "#64748b",       # Muted/disabled text
    "text_accent": "#22d3ee",      # Accent text (cyan)

    # Accent
    "accent": "#22d3ee",           # Primary accent (cyan)
    "accent_hover": "#06b6d4",     # Accent hover
    "accent_dim": "#164e63",       # Dimmed accent for backgrounds

    # Status
    "success": "#10b981",          # Green — connected/recording
    "warning": "#f59e0b",          # Amber — connecting
    "error": "#ef4444",            # Red — error/disconnected
    "info": "#3b82f6",             # Blue — info

    # Charts
    "chart_ecg": "#22d3ee",        # Cyan for ECG trace
    "chart_acc_x": "#f43f5e",      # Rose for ACC X
    "chart_acc_y": "#10b981",      # Emerald for ACC Y
    "chart_acc_z": "#a78bfa",      # Violet for ACC Z
    "chart_hr": "#f59e0b",         # Amber for HR
    "chart_rr": "#818cf8",         # Indigo for RR intervals
    "chart_grid": "#1e293b",       # Subtle grid lines
    "chart_bg": "#0a0e17",         # Chart background
}


# ─── Stylesheet ─────────────────────────────────────────────────────────────────
STYLESHEET = f"""
/* ─── Global ─────────────────────────────────────────────────────── */
QMainWindow {{
    background-color: {COLORS['bg_primary']};
}}

QWidget {{
    background-color: {COLORS['bg_primary']};
    color: {COLORS['text_primary']};
    font-family: 'Inter', 'Segoe UI', 'Roboto', sans-serif;
    font-size: 13px;
}}

/* ─── Scroll Areas ───────────────────────────────────────────────── */
QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollBar:vertical {{
    background-color: {COLORS['bg_secondary']};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['border']};
    min-height: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['text_muted']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ─── Labels ─────────────────────────────────────────────────────── */
QLabel {{
    background-color: transparent;
    padding: 2px;
}}

QLabel[class="title"] {{
    font-size: 20px;
    font-weight: 700;
    color: {COLORS['text_primary']};
    letter-spacing: 1px;
}}

QLabel[class="subtitle"] {{
    font-size: 14px;
    color: {COLORS['text_secondary']};
}}

QLabel[class="stat-value"] {{
    font-size: 28px;
    font-weight: 700;
    color: {COLORS['accent']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
}}

QLabel[class="stat-label"] {{
    font-size: 11px;
    color: {COLORS['text_muted']};
    text-transform: uppercase;
    letter-spacing: 1px;
}}

/* ─── Buttons ────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 600;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {COLORS['bg_hover']};
    border-color: {COLORS['accent']};
}}

QPushButton:pressed {{
    background-color: {COLORS['accent_dim']};
}}

QPushButton:disabled {{
    color: {COLORS['text_muted']};
    background-color: {COLORS['bg_secondary']};
    border-color: {COLORS['bg_secondary']};
}}

QPushButton[class="primary"] {{
    background-color: {COLORS['accent']};
    color: {COLORS['bg_primary']};
    border: none;
    font-weight: 700;
}}

QPushButton[class="primary"]:hover {{
    background-color: {COLORS['accent_hover']};
}}

QPushButton[class="primary"]:disabled {{
    background-color: {COLORS['accent_dim']};
    color: {COLORS['text_muted']};
}}

QPushButton[class="danger"] {{
    background-color: transparent;
    color: {COLORS['error']};
    border-color: {COLORS['error']};
}}

QPushButton[class="danger"]:hover {{
    background-color: {COLORS['error']};
    color: white;
}}

QPushButton[class="success"] {{
    background-color: {COLORS['success']};
    color: white;
    border: none;
    font-weight: 700;
}}

QPushButton[class="success"]:hover {{
    background-color: #059669;
}}

/* ─── Group Boxes / Cards ────────────────────────────────────────── */
QGroupBox {{
    background-color: {COLORS['bg_secondary']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    margin-top: 24px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    color: {COLORS['text_secondary']};
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

/* ─── Combo Box ──────────────────────────────────────────────────── */
QComboBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 18px;
}}

QComboBox:hover {{
    border-color: {COLORS['accent']};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    selection-background-color: {COLORS['accent_dim']};
    selection-color: {COLORS['accent']};
    padding: 4px;
}}

/* ─── Check Box ──────────────────────────────────────────────────── */
QCheckBox {{
    spacing: 8px;
    color: {COLORS['text_primary']};
    background-color: transparent;
}}

QCheckBox[class="ecg"] {{
    color: {COLORS['chart_ecg']};
}}

QCheckBox[class="acc"] {{
    color: {COLORS['chart_acc_x']};
}}

QCheckBox[class="hr"] {{
    color: {COLORS['chart_hr']};
}}

/* ─── Spin Box ───────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 6px 10px;
}}

QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {COLORS['accent']};
}}

/* ─── Line Edit ──────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 12px;
}}

QLineEdit:focus {{
    border-color: {COLORS['accent']};
}}

/* ─── List Widget ────────────────────────────────────────────────── */
QListWidget {{
    background-color: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 10px 12px;
    border-radius: 6px;
    margin: 2px;
}}

QListWidget::item:hover {{
    background-color: {COLORS['bg_hover']};
}}

QListWidget::item:selected {{
    background-color: {COLORS['accent_dim']};
    color: {COLORS['accent']};
}}

/* ─── Tab Widget ─────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    background-color: {COLORS['bg_secondary']};
    top: -1px;
}}

QTabBar::tab {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_secondary']};
    border: 1px solid {COLORS['border']};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 20px;
    margin-right: 2px;
    font-weight: 600;
}}

QTabBar::tab:selected {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['accent']};
    border-bottom: 2px solid {COLORS['accent']};
}}

QTabBar::tab:hover:!selected {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_primary']};
}}

/* ─── Progress Bar ───────────────────────────────────────────────── */
QProgressBar {{
    background-color: {COLORS['bg_input']};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 4px;
}}

/* ─── Status Bar ─────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['text_secondary']};
    border-top: 1px solid {COLORS['border']};
    padding: 4px 12px;
    font-size: 12px;
}}

/* ─── Splitter ───────────────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {COLORS['border']};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

/* ─── Tool Tips ──────────────────────────────────────────────────── */
QToolTip {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ─── Text Edit / Log ────────────────────────────────────────────── */
QTextEdit, QPlainTextEdit {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_secondary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px;
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}}
"""
