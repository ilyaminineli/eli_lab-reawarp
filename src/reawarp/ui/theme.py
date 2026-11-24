"""Monochrome editorial visual language adapted from eli_lab AVTranslator."""

APP_STYLE = """
QMainWindow, QDialog, QMessageBox, QWidget { background: #090909; color: #eeeeee; }
QWidget { font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 9pt; }
QLabel { background: transparent; color: #e5e5e5; }
QMenuBar { background: #090909; color: #bdbdbd; border-bottom: 1px solid #252525; padding: 2px 8px; }
QMenuBar::item { background: transparent; padding: 5px 9px; }
QMenuBar::item:selected { background: #171717; color: #fff; }
QMenu { background: #101010; color: #eee; border: 1px solid #383838; padding: 5px; }
QMenu::item { padding: 7px 28px 7px 12px; }
QMenu::item:selected { background: #e8e8e8; color: #090909; }
QToolBar { background: #090909; border: 0; spacing: 10px; padding: 7px 12px; }
QToolBar::separator { width: 1px; background: #303030; margin: 5px 7px; }
QStatusBar { background: #101010; border-top: 1px solid #303030; color: #a3a3a3; padding: 3px 9px; min-height: 22px; }
QDockWidget { background: #101010; color: #eee; }
QDockWidget::title { background: #101010; color: #a3a3a3; padding: 9px 12px; border-bottom: 1px solid #303030; text-align: left; font-size: 8.5pt; }
QTabWidget::pane { background: #101010; border: 0; border-top: 1px solid #303030; }
QTabBar { background: #090909; qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; color: #888; padding: 6px 10px; min-height: 20px; border: 0; border-bottom: 2px solid transparent; font-size: 8pt; }
QTabBar::tab:hover { color: #eee; background: #111; }
QTabBar::tab:selected { color: #fff; border-bottom: 2px solid #eee; }
QGroupBox { background: #0e0e0e; color: #e5e5e5; border: 1px solid #303030; border-radius: 1px; margin-top: 15px; padding: 14px 12px 11px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 7px; color: #c2c2c2; background: #0e0e0e; font-size: 8.5pt; letter-spacing: 0.7px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QListWidget, QTreeWidget, QTableWidget { background: #0d0d0d; color: #eee; border: 1px solid #303030; border-radius: 1px; padding: 7px 9px; min-height: 22px; selection-background-color: #dedede; selection-color: #090909; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover, QTextEdit:hover { border-color: #4a4a4a; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid #969696; }
QLabel#eyebrow, QLabel#muted, QLabel#mutedLabel { color: #969696; font-size: 8pt; }
QLabel#sectionHeading { color: #f0f0f0; font-family: "Newsreader", "Georgia", "Yu Mincho", serif; font-size: 18px; font-weight: 400; padding: 4px 0 7px; }
QLabel#panelSubheading { color: #c8c8c8; font-family: "Newsreader", "Georgia", serif; font-size: 11pt; padding: 3px 0 5px; }
QLabel#brand { color: #eee; font-family: "Yu Mincho", "Noto Serif JP", "Georgia", serif; font-size: 22pt; font-weight: 500; }
QLabel#brandMark { color: #eee; font-family: "Yu Mincho", "Noto Serif JP", serif; font-size: 27pt; }
QLabel#brandName { color: #d0d0d0; font-family: "DM Mono", "Consolas", monospace; font-size: 8pt; letter-spacing: 1px; }
QLabel#sectionTitle, QLabel#fieldCaption { color: #a3a3a3; font-family: "DM Mono", "Consolas", monospace; font-size: 8pt; letter-spacing: 0.08em; }
QPushButton { background: #151515; color: #e8e8e8; border: 1px solid #343434; border-radius: 1px; padding: 8px 13px; min-height: 25px; }
QPushButton:hover { background: #202020; border-color: #6a6a6a; }
QPushButton:pressed { background: #303030; }
QPushButton:checked { background: #ededed; color: #090909; border-color: #ededed; }
QPushButton:disabled { background: #101010; color: #626262; border-color: #262626; }
QPushButton#primaryAction { background: #ededed; color: #090909; border-color: #ededed; font-weight: 700; }
QToolButton { background: transparent; color: #dedede; border: 1px solid transparent; border-radius: 1px; padding: 5px; }
QToolButton:hover { background: #181818; border-color: #424242; }
QToolButton:checked { background: #ededed; color: #101010; border-color: #ededed; }
QCheckBox, QRadioButton { spacing: 7px; color: #d7d7d7; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; background: #101010; border: 1px solid #737373; }
QCheckBox::indicator { border-radius: 1px; }
QRadioButton::indicator { border-radius: 7px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #eee; border-color: #eee; }
QSlider::groove:horizontal { height: 2px; background: #3c3c3c; }
QSlider::sub-page:horizontal { background: #cfcfcf; }
QSlider::add-page:horizontal { background: #292929; }
QSlider::handle:horizontal { width: 11px; height: 11px; margin: -5px 0; background: #eee; border: 1px solid #eee; border-radius: 6px; }
QProgressBar { background: #141414; border: 1px solid #303030; color: #eaeaea; text-align: center; min-height: 8px; }
QProgressBar::chunk { background: #bdbdbd; }
QScrollArea { border: 0; background: transparent; }
QSplitter::handle { background: #282828; }
QSplitter::handle:hover { background: #595959; }
QScrollBar:vertical, QScrollBar:horizontal { background: #101010; width: 10px; height: 10px; border: 0; margin: 0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #3d3d3d; min-height: 24px; min-width: 24px; border: 2px solid #101010; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QToolTip { background: #151515; color: #eee; border: 1px solid #555; padding: 5px 7px; }
QMessageBox QLabel { color: #eee; min-width: 280px; }
QFrame#header { background: #090909; border-bottom: 1px solid #252525; }
QFrame#transportBar { background: #101010; border: 1px solid #303030; }
QFrame#workspaceHeader { background: #0b0b0b; border-bottom: 1px solid #282828; }
QFrame#emptyState { background: #0d0d0d; border: 1px solid #303030; }
QLabel#workspaceTitle { color: #f0f0f0; font-family: "Newsreader", "Georgia", serif; font-size: 15pt; font-weight: 400; }
QLabel#projectContext { color: #a6a6a6; font-family: "DM Mono", "Consolas", monospace; font-size: 7.5pt; letter-spacing: 0.04em; }
QTreeWidget#workspaceNavigator { background: #0c0c0c; border: 1px solid #292929; padding: 7px 5px; outline: 0; }
QTreeWidget#workspaceNavigator::item { padding: 8px 8px; margin: 1px 2px; border: 0; }
QTreeWidget#workspaceNavigator::item:hover { background: #171717; color: #fff; }
QTreeWidget#workspaceNavigator::item:selected { background: #e7e7e7; color: #090909; }
QTreeWidget#workspaceNavigator::branch { background: transparent; }
QTreeWidget#workspaceNavigator::item:has-children { color: #858585; font-family: "DM Mono", "Consolas", monospace; font-size: 7.5pt; font-weight: 600; padding-top: 12px; padding-bottom: 5px; }
"""
