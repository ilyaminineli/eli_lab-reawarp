"""Dark laboratory visual language for the Reawarp desktop application."""

APP_STYLE = """
QMainWindow, QWidget { background: #171b22; color: #e5e9f0; font-family: "Segoe UI"; font-size: 10pt; }
QMenuBar, QMenu, QTabWidget::pane { background: #171b22; border: 1px solid #303744; }
QTabBar::tab { background: #202631; color: #9ba7b7; padding: 10px 16px; margin-right: 3px; border-top-left-radius: 5px; border-top-right-radius: 5px; }
QTabBar::tab:selected { background: #2a3442; color: #f5f7fa; border-bottom: 2px solid #6e9fe8; }
QGroupBox { border: 1px solid #303744; border-radius: 7px; margin-top: 12px; padding: 12px 10px 10px 10px; font-weight: 600; color: #b9c8dc; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { background: #10151c; color: #e5e9f0; border: 1px solid #384252; border-radius: 4px; padding: 6px; }
QComboBox QAbstractItemView { background: #1d2530; selection-background-color: #36577f; }
QPushButton { background: #2a3544; border: 1px solid #445267; border-radius: 5px; color: #e8eef7; padding: 7px 12px; }
QPushButton:hover { background: #35465b; }
QPushButton:pressed { background: #263343; }
QPushButton:disabled { color: #697482; background: #202630; }
QPushButton#primaryAction { background: #416da7; border-color: #5a8ccc; color: white; font-weight: 700; padding: 10px 18px; }
QPushButton#primaryAction:hover { background: #4d7dbb; }
QToolButton { background: #252e3a; border: 1px solid #3c4858; border-radius: 4px; padding: 5px 9px; }
QToolButton:checked { background: #68503a; border-color: #bb8a50; color: #fff1dc; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #566273; border-radius: 3px; background: #10151c; }
QCheckBox::indicator:checked { background: #5e8dc9; border-color: #8bb4ea; }
QProgressBar { border: 1px solid #34404e; border-radius: 4px; background: #10151c; text-align: center; color: #e5e9f0; }
QProgressBar::chunk { background: #577eaf; border-radius: 3px; }
QStatusBar { background: #11161d; color: #a8b4c3; }
QScrollArea { border: none; }
QFrame#header { background: #11161d; border-bottom: 1px solid #303744; }
QLabel#brand { font-size: 17pt; font-weight: 700; letter-spacing: 2px; color: #f2f5fa; }
QLabel#muted { color: #8d9aab; }
QLabel#sectionTitle { color: #8eadd5; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }
"""
