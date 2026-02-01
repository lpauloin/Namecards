import sys
import threading
from datetime import datetime
from pathlib import Path

import trimesh
from pyqtgraph.opengl import GLMeshItem, GLViewWidget, MeshData
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QListWidgetItem, QMessageBox

from pack import DEFAULT_BED_H, DEFAULT_BED_W, DEFAULT_SPACING, pack_outdir
from stl import generate_for_names
from PySide6.QtGui import QFontDatabase

QCoreApplication.setAttribute(Qt.AA_UseDesktopOpenGL)

# =========================================================
# OpenGL STL Viewer
# =========================================================


class STLViewer(GLViewWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setBackgroundColor((120, 120, 120))
        self.opts["ambientLight"] = (0.7, 0.7, 0.7, 1.0)
        self.opts["diffuseLight"] = (1.0, 1.0, 1.0, 1.0)
        self.setCameraPosition(distance=300)

    def clear_view(self):
        self.clear()

    def show_stl(self, path: Path):
        self.clear()

        mesh = trimesh.load_mesh(path, force="mesh")
        verts = mesh.vertices

        meshdata = MeshData(vertexes=verts, faces=mesh.faces)
        item = GLMeshItem(
            meshdata=meshdata,
            smooth=False,
            shader="shaded",
            drawEdges=True,
            edgeColor=(0.05, 0.1, 0.2, 1.0),
            color=(0.75, 0.82, 0.90, 1.0),
        )

        # Center mesh
        center = verts.mean(axis=0)
        item.translate(-center[0], -center[1], -center[2])
        self.addItem(item)

        # Face the text (XY plane)
        size = verts.max(axis=0) - verts.min(axis=0)
        longest = max(size[0], size[1])

        self.setCameraPosition(
            distance=max(250, longest * 2.5),
            elevation=90,
            azimuth=0,
        )


# =========================================================
# Main Window
# =========================================================


class MainWindow(QtWidgets.QMainWindow):
    WATCH_INTERVAL_MS = 500

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Namecards — STL & Plates")
        self.resize(1900, 1000)

        self.outdir = Path.cwd() / "output"

        # Preview tracking
        self.preview_path: Path | None = None
        self.preview_mtime: float | None = None

        # Filesystem watcher state
        self._fs_state: dict[str, float] = {}

        self._build_ui()
        self._init_names_from_stl()
        self._refresh_all()

        # Periodic watcher
        self._watch_timer = QtCore.QTimer(self)
        self._watch_timer.setInterval(self.WATCH_INTERVAL_MS)
        self._watch_timer.timeout.connect(self._watch_filesystem)
        self._watch_timer.start()

    # =====================================================
    # Paths
    # =====================================================

    def stl_dir(self) -> Path:
        return self.outdir / "stl"

    def plate_dir(self) -> Path:
        return self.outdir / "plate"

    # =====================================================
    # UI
    # =====================================================

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        # ===== LEFT COLUMN =====
        left = QtWidgets.QVBoxLayout()
        root.addLayout(left, 0)

        # ---- OUTDIR box
        out_box = QtWidgets.QGroupBox("Output directory")
        out_layout = QtWidgets.QVBoxLayout(out_box)
        left.addWidget(out_box)

        self.outdir_path = QtWidgets.QLineEdit()
        self.outdir_path.setReadOnly(True)
        self.outdir_path.setFont(QtGui.QFont("Menlo", 11))
        out_layout.addWidget(self.outdir_path)

        self.outdir_status = QtWidgets.QLabel()
        out_layout.addWidget(self.outdir_status)

        out_btns = QtWidgets.QHBoxLayout()
        out_layout.addLayout(out_btns)

        btn_open = QtWidgets.QPushButton("Open")
        btn_open.clicked.connect(self._open_outdir)
        out_btns.addWidget(btn_open)

        btn_reset = QtWidgets.QPushButton("Reset")
        btn_reset.clicked.connect(self._reset_outdir)
        out_btns.addWidget(btn_reset)

        btn_choose = QtWidgets.QPushButton("Choose…")
        btn_choose.clicked.connect(self._choose_outdir)
        out_btns.addWidget(btn_choose)

        # ---- Font selection
        self.font_combo = QtWidgets.QFontComboBox()
        self.font_combo.setEditable(False)

        # ---- Names
        left.addWidget(QtWidgets.QLabel("Names (one per line):"))
        self.names_edit = QtWidgets.QPlainTextEdit()
        left.addWidget(self.names_edit, 1)

        # ---- STL config
        stl_box = QtWidgets.QGroupBox("STL generation")
        stl_form = QtWidgets.QFormLayout(stl_box)
        left.addWidget(stl_box)

        self.min_font = self._spin(stl_form, "min_font", 14, 8, 100)
        self.max_font = self._spin(stl_form, "max_font", 22, 8, 100)
        self.offset_min = self._dspin(stl_form, "offset_min", 3.0, 0, 50)
        self.offset_max = self._dspin(stl_form, "offset_max", 18.0, 0, 50)

        # Try to select default font
        if "Bona Nova SC" in QFontDatabase.families():
            self.font_combo.setCurrentFont(QtGui.QFont("Bona Nova SC"))
        # Restrict to Latin
        self.font_combo.setWritingSystem(QtGui.QFontDatabase.Latin)

        stl_form.addRow("font_family", self.font_combo)

        # ---- Plate config
        plate_box = QtWidgets.QGroupBox("STL plates (packing)")
        plate_form = QtWidgets.QFormLayout(plate_box)
        left.addWidget(plate_box)

        self.bed_w = self._dspin(plate_form, "bed_w", DEFAULT_BED_W, 50, 1000, 1)
        self.bed_h = self._dspin(plate_form, "bed_h", DEFAULT_BED_H, 50, 1000, 1)
        self.spacing = self._dspin(plate_form, "spacing", DEFAULT_SPACING, 0, 100, 2)

        # ===== STL LIST =====
        stl_col = QtWidgets.QVBoxLayout()
        root.addLayout(stl_col, 0)

        stl_col.addWidget(QtWidgets.QLabel("STL files"))
        self.stl_list = QtWidgets.QListWidget()
        self.stl_list.itemClicked.connect(self._on_item_selected)
        self.stl_list.currentItemChanged.connect(self._on_item_selected)
        stl_col.addWidget(self.stl_list, 1)

        self._add_buttons(
            stl_col,
            generate=self._generate_stl,
            delete=self._delete_selected_stl,
            delete_all=self._delete_all_stl,
        )

        # ===== PLATE LIST =====
        plate_col = QtWidgets.QVBoxLayout()
        root.addLayout(plate_col, 0)

        plate_col.addWidget(QtWidgets.QLabel("STL plates"))
        self.plate_list = QtWidgets.QListWidget()
        self.plate_list.itemClicked.connect(self._on_item_selected)
        self.plate_list.currentItemChanged.connect(self._on_item_selected)
        plate_col.addWidget(self.plate_list, 1)

        self._add_buttons(
            plate_col,
            generate=self._generate_plates,
            delete=self._delete_selected_plate,
            delete_all=self._delete_all_plates,
        )

        # ===== VIEWER =====
        self.viewer = STLViewer()
        root.addWidget(self.viewer, 1)

    # =====================================================
    # UI helpers
    # =====================================================

    def _spin(self, layout, label, value, lo, hi):
        w = QtWidgets.QSpinBox()
        w.setRange(lo, hi)
        w.setValue(value)
        layout.addRow(label, w)
        return w

    def _dspin(self, layout, label, value, lo, hi, decimals=2):
        w = QtWidgets.QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setDecimals(decimals)
        w.setValue(value)
        layout.addRow(label, w)
        return w

    def _add_buttons(self, parent_layout, *, generate, delete, delete_all):
        row = QtWidgets.QHBoxLayout()
        parent_layout.addLayout(row)

        for text, cb in [
            ("Generate", generate),
            ("Delete", delete),
            ("Delete All", delete_all),
        ]:
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(cb)
            row.addWidget(b)

    # =====================================================
    # OUTDIR UX
    # =====================================================

    def _update_outdir_ui(self):
        self.outdir_path.setText(str(self.outdir.resolve()))

        stl = self.stl_dir()
        plate = self.plate_dir()

        stl_count = len(list(stl.glob("*.stl"))) if stl.exists() else 0
        plate_count = len(list(plate.glob("*.stl"))) if plate.exists() else 0

        self.outdir_status.setText(
            f"{'✔' if stl.exists() else '✖'} STL: {stl_count}   "
            f"{'✔' if plate.exists() else '✖'} Plates: {plate_count}"
        )

    def _open_outdir(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.outdir)))

    def _reset_outdir(self):
        self.outdir = Path.cwd() / "output"
        self._on_outdir_changed()

    def _choose_outdir(self):
        path = QFileDialog.getExistingDirectory(self, "Select OUTDIR")
        if path:
            self.outdir = Path(path)
            self._on_outdir_changed()

    def _on_outdir_changed(self):
        self.preview_path = None
        self.preview_mtime = None
        self.viewer.clear_view()
        self._init_names_from_stl()
        self._refresh_all()

    # =====================================================
    # Init
    # =====================================================

    def _init_names_from_stl(self):
        default = "Laurent Pauloin\nJean Dupont"
        d = self.stl_dir()

        if not d.exists():
            self.names_edit.setPlainText(default)
            return

        stls = list(d.glob("*.stl"))
        if not stls:
            self.names_edit.setPlainText(default)
            return

        self.names_edit.setPlainText("\n".join(p.stem for p in stls))

    # =====================================================
    # Generate
    # =====================================================

    def _generate_stl(self):
        names = [
            n.strip() for n in self.names_edit.toPlainText().splitlines() if n.strip()
        ]
        if not names:
            return

        def worker():
            generate_for_names(
                names,
                font_family=self.font_combo.currentFont().family(),
                min_font=self.min_font.value(),
                max_font=self.max_font.value(),
                offset_min=self.offset_min.value(),
                offset_max=self.offset_max.value(),
                output_dir=self.outdir,
            )
            QtCore.QTimer.singleShot(0, self._refresh_all)

        threading.Thread(target=worker, daemon=True).start()

    def _generate_plates(self):
        def worker():
            pack_outdir(
                outdir=self.outdir,
                bed_w=self.bed_w.value(),
                bed_h=self.bed_h.value(),
                spacing=self.spacing.value(),
            )
            QtCore.QTimer.singleShot(0, self._refresh_all)

        threading.Thread(target=worker, daemon=True).start()

    # =====================================================
    # Delete
    # =====================================================

    def _delete_selected_stl(self):
        self._delete_selected(self.stl_list)

    def _delete_selected_plate(self):
        self._delete_selected(self.plate_list)

    def _delete_all_stl(self):
        self._delete_all(self.stl_dir())

    def _delete_all_plates(self):
        self._delete_all(self.plate_dir())

    def _delete_selected(self, widget):
        item = widget.currentItem()
        if not item:
            return
        path: Path = item.data(QtCore.Qt.UserRole)
        path.unlink(missing_ok=True)
        if path == self.preview_path:
            self.viewer.clear_view()
            self.preview_path = None
        self._refresh_all()

    def _delete_all(self, folder: Path):
        if not folder.exists():
            return
        if (
            QMessageBox.question(self, "Confirm", f"Delete ALL in {folder.name}?")
            != QMessageBox.Yes
        ):
            return
        for p in folder.glob("*.stl"):
            p.unlink(missing_ok=True)
        self.viewer.clear_view()
        self.preview_path = None
        self._refresh_all()

    # =====================================================
    # Preview
    # =====================================================

    def _on_item_selected(self, item: QListWidgetItem, previous=None):
        if not item:
            return

        path: Path = item.data(QtCore.Qt.UserRole)
        if not path or not path.exists():
            return

        self.viewer.show_stl(path)
        self.preview_path = path
        self.preview_mtime = path.stat().st_mtime

    def _refresh_preview_if_needed(self):
        if not self.preview_path or not self.preview_path.exists():
            return
        mtime = self.preview_path.stat().st_mtime
        if mtime != self.preview_mtime:
            self.viewer.show_stl(self.preview_path)
            self.preview_mtime = mtime

    # =====================================================
    # Refresh + watcher
    # =====================================================

    def _refresh_all(self):
        self._refresh_list(self.stl_list, self.stl_dir())
        self._refresh_list(self.plate_list, self.plate_dir())
        self._refresh_preview_if_needed()
        self._update_outdir_ui()

    def _refresh_list(self, widget, folder: Path):
        widget.clear()
        if not folder.exists():
            return
        for p in sorted(
            folder.glob("*.stl"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            item = QListWidgetItem(f"{p.name}  [{ts}]")
            item.setData(QtCore.Qt.UserRole, p)
            widget.addItem(item)

    def _watch_filesystem(self):
        state = {}
        for folder in (self.stl_dir(), self.plate_dir()):
            if folder.exists():
                for p in folder.glob("*.stl"):
                    try:
                        state[str(p)] = p.stat().st_mtime
                    except FileNotFoundError:
                        pass
        if state != self._fs_state:
            self._fs_state = state
            self._refresh_all()


# =========================================================
# Entry point
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
