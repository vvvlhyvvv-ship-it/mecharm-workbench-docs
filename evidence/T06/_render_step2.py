"""Offscreen render of Step2Pane at narrow widths — criterion 8 (列表不越界)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import app  # noqa: F401  ICU preload before any PySide6.QtWidgets import
from PySide6.QtWidgets import QApplication
from core.geometry.face_point import FacePoint
from app.steps.step2_pick import Step2Pane

OUT = os.path.dirname(os.path.abspath(__file__))
qapp = QApplication([])

pane = Step2Pane()
pane.set_mode("多功能臂A")            # unlock (criterion 5: right-column top line shows mode)
pane.add_face_point(FacePoint(pos_mm=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0), source_face=1))
pane.add_face_point(FacePoint(pos_mm=(20.0, 12.0, 8.0), normal=(0.0, 0.0, 1.0), source_face=2))
# deliberately wide coordinate text to stress horizontal fit
pane.add_face_point(FacePoint(pos_mm=(1234.567, 78.901, 1011.121), normal=(1.0, 0.0, 0.0),
                              source_face=3))
# duplicate face → must NOT add a 4th (criterion 3 dedup)
pane.add_face_point(FacePoint(pos_mm=(5.0, 5.0, 5.0), normal=(0.0, 1.0, 0.0), source_face=2))

print("waypoint count (expect 3, dup face_2 rejected):", len(pane.waypoints()))
print("ids (no renumber):", [w.id for w in pane.waypoints()])
print("names:", [w.name for w in pane.waypoints()])
print("mode line:", pane._mode_line.text())

for width in (280, 360):
    pane.resize(width, 500)
    pane.show()
    qapp.processEvents()
    t = pane._table
    hsb = t.horizontalScrollBar()
    cols = t.columnCount()
    hdr = t.horizontalHeader()
    sec_w = [hdr.sectionSize(c) for c in range(cols)]
    last_visible = hdr.sectionViewportPosition(cols - 1) + hdr.sectionSize(cols - 1)
    overflow = last_visible > t.viewport().width() + 1
    print(f"\n--- width={width} ---")
    print(f"  table.viewport.width={t.viewport().width()}  sum(section widths)={sum(sec_w)}")
    print(f"  section widths={sec_w}")
    print(f"  horizontalScrollBar.maximum={hsb.maximum()} (0 => no horizontal overflow)")
    print(f"  last col right edge={last_visible}  viewport={t.viewport().width()}  overflow={overflow}")
    print(f"  pane.width={pane.width()} (<= requested {width}: {pane.width() <= width})")
    pix = pane.grab()
    path = os.path.join(OUT, f"step2_list_{width}x500.png")
    pix.save(path)
    print(f"  grabbed {pix.width()}x{pix.height()} -> {path}")
