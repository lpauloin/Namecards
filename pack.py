from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math
import trimesh


# =========================================================
# DEFAULT CONFIG (Ender 3 V2)
# =========================================================

DEFAULT_BED_W = 215.0
DEFAULT_BED_H = 215.0
DEFAULT_SPACING = 3.0


# =========================================================


@dataclass
class Item:
    path: Path
    mesh: trimesh.Trimesh
    w: float
    h: float


@dataclass
class Placed:
    item: Item
    x: float
    y: float
    rot90: bool


# =========================================================
# Mesh helpers
# =========================================================


def load_mesh(path: Path) -> trimesh.Trimesh:
    m = trimesh.load_mesh(path, force="mesh")
    m = trimesh.util.concatenate(m)
    return m


def mesh_xy(mesh: trimesh.Trimesh) -> tuple[float, float]:
    b = mesh.bounds
    return float(b[1, 0] - b[0, 0]), float(b[1, 1] - b[0, 1])


def place_on_z0(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    m = mesh.copy()
    zmin = float(m.bounds[0, 2])
    m.apply_translation([0, 0, -zmin])
    return m


def rotate90(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    m = mesh.copy()
    R = trimesh.transformations.rotation_matrix(math.pi / 2, [0, 0, 1])
    m.apply_transform(R)
    return m


# =========================================================
# Packing algorithm (multi-plate)
# =========================================================


def pack_items(
    items: list[Item],
    bed_w: float,
    bed_h: float,
    spacing: float,
) -> list[list[Placed]]:
    plates: list[list[Placed]] = []
    remaining = items[:]

    while remaining:
        x = spacing
        y = spacing
        row_h = 0.0
        plate: list[Placed] = []
        next_remaining: list[Item] = []

        for item in remaining:
            placed = False
            for rot in (False, True):
                w, h = (item.w, item.h) if not rot else (item.h, item.w)
                if x + w + spacing <= bed_w and y + h + spacing <= bed_h:
                    plate.append(Placed(item, x, y, rot))
                    x += w + spacing
                    row_h = max(row_h, h)
                    placed = True
                    break

            if placed:
                continue

            # new row
            x = spacing
            y += row_h + spacing
            row_h = 0.0

            for rot in (False, True):
                w, h = (item.w, item.h) if not rot else (item.h, item.w)
                if x + w + spacing <= bed_w and y + h + spacing <= bed_h:
                    plate.append(Placed(item, x, y, rot))
                    x += w + spacing
                    row_h = max(row_h, h)
                    placed = True
                    break

            if not placed:
                next_remaining.append(item)

        if not plate:
            raise RuntimeError("❌ Une pièce est trop grande pour le plateau.")

        plates.append(plate)
        remaining = next_remaining

    return plates


# =========================================================
# Public API (GUI + CLI)
# =========================================================


def pack_outdir(
    outdir: Path,
    bed_w: float = DEFAULT_BED_W,
    bed_h: float = DEFAULT_BED_H,
    spacing: float = DEFAULT_SPACING,
) -> list[Path]:
    stl_dir = outdir / "stl"
    plate_dir = outdir / "plate"
    plate_dir.mkdir(exist_ok=True)

    stls = sorted(stl_dir.glob("*.stl"))
    if not stls:
        raise RuntimeError("❌ Aucun STL trouvé dans outdir/stl")

    items: list[Item] = []
    for p in stls:
        m = place_on_z0(load_mesh(p))
        w, h = mesh_xy(m)
        items.append(Item(p, m, w, h))

    # sort by area desc
    items.sort(key=lambda i: i.w * i.h, reverse=True)

    plates = pack_items(items, bed_w, bed_h, spacing)

    outputs: list[Path] = []

    for i, plate in enumerate(plates, start=1):
        meshes = []
        print(f"🟩 Génération plate {i:02d}")

        for p in plate:
            m = p.item.mesh
            if p.rot90:
                m = rotate90(m)
                m = place_on_z0(m)

            b = m.bounds
            dx = p.x - float(b[0, 0])
            dy = p.y - float(b[0, 1])
            m = m.copy()
            m.apply_translation([dx, dy, 0])
            meshes.append(m)

            print(
                f"   • {p.item.path.name} "
                f"(rot90={p.rot90}) "
                f"@ x={p.x:.1f} y={p.y:.1f}"
            )

        combo = trimesh.util.concatenate(meshes)
        out = plate_dir / f"plate_{i:02d}.stl"
        combo.export(out)
        outputs.append(out)

        print(f"✅ Plate {i:02d} → {out.resolve()}\n")

    return outputs


# =========================================================
# CLI
# =========================================================


def main():
    outdir = Path("output")
    pack_outdir(outdir)


if __name__ == "__main__":
    main()
