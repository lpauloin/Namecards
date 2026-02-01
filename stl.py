import re
import subprocess
import unicodedata
from pathlib import Path

import trimesh

from utils import resource_path


def run(cmd, cwd=None):
    """Run a shell command and fail loudly if it errors."""
    print("▶ RUN:", " ".join(map(str, cmd)))
    subprocess.run(cmd, cwd=cwd, check=True)


def clamp(x, lo, hi):
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, x))


def weighted_len(s: str, debug=True) -> float:
    """
    Compute a weighted visual length for a string.

    Characters have different visual widths depending on:
    - uppercase vs lowercase
    - wide letters (W, M)
    - medium-width letters
    - spaces and hyphens

    This is used to better estimate how long a name appears
    when rendered along a curved SVG path.
    """
    total = 0.0
    if debug:
        print("\n🔍 Computing weighted length:", s)

    for ch in s:
        # Base weight
        w = 1.0
        reason = "base"

        if ch in set(" -"):
            w = 1.4
            reason = "hyphen-space"

        else:
            # Standard uppercase letters
            if ch.isupper():
                w *= 1.4
                reason = "uppercase"

            # Extra-wide letters
            if ch in set("WM"):
                w *= 1.8
                reason += "+wide"

            # Medium-width letters
            elif ch in set("VNHCOUDG"):
                w *= 1.2
                reason += "+medium"

        total += w

        if debug:
            print(f"   '{ch}' → {w:.2f} ({reason})")

    if debug:
        print(f"➡ weighted_len = {total:.2f}")

    return total


def compute_layout(
    name: str,
    ref_name: str,
    ref_font: int,
    ref_offset: float,
    text_length: float,
    min_font=14,
    max_font=22,
    offset_min=3.0,
    offset_max=18.0,
    debug=True,
):
    """
    Compute font size and SVG textPath offset for a given name.

    The layout is computed relative to a reference name with
    known good parameters, using a non-linear scaling model
    to preserve visual balance.
    """
    print("\n================ LAYOUT COMPUTATION ================")
    print(f"Name: '{name}'")

    ref_len = weighted_len(ref_name, debug)
    cur_len = weighted_len(name, debug)

    print("\n📏 Length comparison:")
    print(f"   ref_len = {ref_len:.2f}")
    print(f"   cur_len = {cur_len:.2f}")

    # ---------- Font size computation ----------
    exponent = 1.08
    ratio = (ref_len / cur_len) ** exponent
    raw_font = ref_font * ratio
    font = int(round(raw_font))
    font = int(clamp(font, min_font, max_font))

    print("\n🔠 Font-size computation:")
    print(f"   exponent = {exponent}")
    print(f"   ratio = {ratio:.4f}")
    print(f"   raw_font = {raw_font:.2f}")
    print(f"   clamped font = {font}")

    # ---------- SVG textPath startOffset ----------
    k = 0.22
    delta = cur_len - ref_len
    raw_offset = ref_offset - k * (delta**0.6 if delta > 0 else delta)
    raw_offset += 1.5
    offset = clamp(raw_offset, offset_min, offset_max)

    print("\n↔ startOffset computation:")
    print(f"   delta_len = {delta:.2f}")
    print(f"   raw_offset = {raw_offset:.2f}")
    print(f"   clamped offset = {offset:.2f}")

    print("\n📐 Final layout:")
    print(f"   font-size = {font}")
    print(f"   startOffset = {offset:.2f}%")
    print(f"   textLength = {text_length}%")
    print("====================================================\n")

    return font, offset, text_length


# =========================================================
# SVG / STL pipeline
# =========================================================


def project_stl_to_svg(scad_path: Path, stl_path: Path, out_svg: Path, workdir: Path):
    """
    Project a 3D STL into a 2D SVG using OpenSCAD projection.
    """
    scad_path.write_text(
        f"""\
projection(cut=false)
mirror([1, 0, 0])
    import("{stl_path.resolve()}");
""",
        encoding="utf-8",
    )
    run(["openscad", "-o", out_svg.resolve(), scad_path.resolve()])


def parse_projected_svg(svg_path: Path):
    """
    Parse the projected SVG to extract:
    - viewBox
    - the longest path (used as text guide)
    - all shape paths
    """
    src = svg_path.read_text(encoding="utf-8")

    m = re.search(r'viewBox="([^"]+)"', src)
    viewbox = m.group(1) if m else "0 0 300 100"

    paths = re.findall(r"<path[^>]*>", src)
    if not paths:
        raise RuntimeError("❌ No <path> found in SVG")

    # Longest path is assumed to be the guide
    guide = max(paths, key=len)

    if "id=" in guide:
        guide = re.sub(r'id="[^"]*"', 'id="guide"', guide)
    else:
        guide = guide.replace("<path", '<path id="guide"', 1)

    if "pathLength=" not in guide:
        guide = guide.replace("<path", '<path pathLength="100"', 1)

    guide = re.sub(r'fill="[^"]*"', 'fill="none"', guide)
    guide = re.sub(r'stroke="[^"]*"', 'stroke="none"', guide)

    shapes = []
    for p in paths:
        p2 = p
        if "fill=" not in p2:
            p2 = p2.replace("<path", '<path fill="black" stroke="none"', 1)
        else:
            p2 = re.sub(r'fill="[^"]*"', 'fill="black"', p2)
            p2 = re.sub(r'stroke="[^"]*"', 'stroke="none"', p2)
        shapes.append(p2)

    return viewbox, guide, shapes


def remove_small_islands(
    mesh: trimesh.Trimesh,
    min_area_ratio: float = 0.015,
    debug: bool = True,
) -> trimesh.Trimesh:
    """
    Remove small disconnected mesh components (dots, accents, noise).

    min_area_ratio:
        Fraction of the largest component surface area.
        0.015 = 1.5%, good default for extruded text.
    """
    components = mesh.split(only_watertight=False)

    if len(components) <= 1:
        if debug:
            print("✔ No detached components detected")
        return mesh

    areas = [c.area for c in components]
    max_area = max(areas)

    if debug:
        print("\n🧹 Cleaning small islands:")
        for i, a in enumerate(areas):
            print(f"   component {i}: area={a:.2f}")

    kept = []
    for comp, area in zip(components, areas):
        ratio = area / max_area
        if ratio >= min_area_ratio:
            kept.append(comp)
        elif debug:
            print(f"   ❌ removed component (ratio={ratio:.4f})")

    if not kept:
        raise RuntimeError("All components were removed (threshold too high)")

    cleaned = trimesh.util.concatenate(kept)

    if debug:
        print(f"✔ Kept {len(kept)} / {len(components)} components")

    return cleaned


def write_name_svg(
    out_svg: Path,
    viewbox: str,
    shape_paths,
    guide_path,
    name: str,
    font_family: str,
    font_weight: str,
    font_size: int,
    start_offset: float,
    text_length: float,
):
    """
    Write the final SVG containing the base shape and the curved text.
    """
    dy = -2.5 if font_size < 16 else -3.5
    out_svg.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">
  {''.join(shape_paths)}
  {guide_path}

  <text font-family="{font_family}"
        font-size="{font_size}"
        font-weight="{font_weight}"
        fill="black">
    <textPath href="#guide"
              startOffset="{start_offset}%"
              textLength="{text_length}"
              lengthAdjust="spacingAndGlyphs"
              dy="{dy}"
              side="right"
              dominant-baseline="middle"
              alignment-baseline="middle">
      {name}
    </textPath>
  </text>
</svg>
""",
        encoding="utf-8",
    )


def svg_to_stl(
    paths_svg: Path,
    name_svg: Path,
    out_stl: Path,
    scad_path: Path,
    scale_xy=2.0,
    height=3.0,
):
    """
    Convert an SVG into an extruded STL using Inkscape and OpenSCAD.
    """
    run(
        [
            "inkscape",
            name_svg.resolve(),
            "--export-text-to-path",
            "--export-plain-svg",
            f"--export-filename={paths_svg.resolve()}",
        ]
    )

    scad_path.write_text(
        f"""
scale([{scale_xy}, {scale_xy}, 1])
    linear_extrude(height={height})
        import("{paths_svg.resolve()}");
""",
        encoding="utf-8",
    )

    run(["openscad", "-o", out_stl.resolve(), scad_path.resolve()])

    # --- Remove small detached mesh artifacts ---
    print("🧹 Cleaning small detached islands...")
    mesh = trimesh.load_mesh(out_stl, force="mesh")
    mesh = remove_small_islands(mesh, min_area_ratio=0.015, debug=True)
    mesh.export(out_stl)


# =========================================================
# Batch API (public entry point)
# =========================================================


def generate_for_names(
    names: list[str],
    *,
    font_family="Bona Nova SC",
    min_font=14,
    max_font=22,
    offset_min=3.0,
    offset_max=18.0,
    output_dir: Path | None = None,
):
    """
    Generate STL name clips for a list of names.
    """
    etc = resource_path("etc")

    if output_dir is None:
        out = Path.cwd() / "output"
    else:
        out = Path(output_dir).resolve()

    out_svg = out / "svg"
    out_stl = out / "stl"
    out_scad = out / "scad"
    out.mkdir(exist_ok=True)
    out_svg.mkdir(exist_ok=True)
    out_stl.mkdir(exist_ok=True)
    out_scad.mkdir(exist_ok=True)

    swooch_stl = etc / "swooch.stl"
    project_scad = out_scad / "project.scad"
    raw_svg = out_svg / "swooch_raw.svg"

    project_stl_to_svg(project_scad, swooch_stl, raw_svg, out_svg)
    viewbox, guide, shapes = parse_projected_svg(raw_svg)

    for raw_name in names:
        print("\n\n############################################")
        print("### GENERATING FOR:", raw_name)
        print("############################################")

        name = unicodedata.normalize("NFC", raw_name)

        font, offset, text_len = compute_layout(
            name=name,
            ref_name="Laurent Pauloin",
            ref_font=18,
            ref_offset=8.8,
            text_length=55.0,
            min_font=min_font,
            max_font=max_font,
            offset_min=offset_min,
            offset_max=offset_max,
        )

        # If the name is very long, split and rebalance it
        if len(name) > 20:
            hyphen_pos = name.rfind(" ")
            prefix = name[:hyphen_pos]
            suffix = name[hyphen_pos + 1 :]

            font, offset, text_len = compute_layout(
                name=prefix,
                ref_name="Laurent Pauloin",
                ref_font=18,
                ref_offset=8.8,
                text_length=55.0,
            )

            prefix_len = len(prefix)
            suffix_len = len(suffix)
            ratio = suffix_len / prefix_len

            if ratio <= 0.4:
                hyphens_count = 4
            elif ratio <= 0.5:
                hyphens_count = 3
            elif ratio <= 0.6:
                hyphens_count = 2
            else:
                hyphens_count = 1

            name = f"{prefix}{'-' * hyphens_count}{suffix}"

        out_name_svg = out_svg / f"{raw_name}.svg"
        out_name_paths_svg = out_svg / f"{raw_name}_paths.svg"
        out_name_stl = out_stl / f"{raw_name}.stl"
        out_name_scad = out_scad / f"{raw_name}.scad"

        write_name_svg(
            out_svg=out_name_svg,
            viewbox=viewbox,
            shape_paths=shapes,
            guide_path=guide,
            name=name,
            font_family=font_family,
            font_weight="bold",
            font_size=font,
            start_offset=offset,
            text_length=text_len,
        )

        svg_to_stl(
            scad_path=out_name_scad,
            paths_svg=out_name_paths_svg,
            name_svg=out_name_svg,
            out_stl=out_name_stl,
        )

        print("✅ DONE:", out_stl.resolve())


# =========================================================
# Example usage
# =========================================================

if __name__ == "__main__":
    generate_for_names(names=["Lolo", "Popo"])
