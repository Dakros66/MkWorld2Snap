from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

from workshop_types import BuildRequestSettings
from u1_packager import forge_package
from reference_catalog import read_project_settings, read_source_settings
from scene_preview import build_preview_scene
from watch_folders import _thumbnail_data_url


MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources>
  <object id="1" type="model">
   <mesh>
    <vertices>
     <vertex x="0" y="0" z="0"/>
     <vertex x="1" y="0" z="0"/>
     <vertex x="0" y="1" z="0"/>
    </vertices>
    <triangles>
     <triangle v1="0" v2="1" v3="2"/>
    </triangles>
   </mesh>
  </object>
 </resources>
 <build>
  <item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
 </build>
</model>
"""


MULTIPLATE_MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources>
  <object id="1" type="model">
   <mesh>
    <vertices>
     <vertex x="0" y="0" z="0"/>
     <vertex x="20" y="0" z="0"/>
     <vertex x="0" y="20" z="0"/>
    </vertices>
    <triangles>
     <triangle v1="0" v2="1" v3="2"/>
    </triangles>
   </mesh>
  </object>
  <object id="2" type="model">
   <mesh>
    <vertices>
     <vertex x="0" y="0" z="0"/>
     <vertex x="20" y="0" z="0"/>
     <vertex x="0" y="20" z="0"/>
    </vertices>
    <triangles>
     <triangle v1="0" v2="1" v3="2"/>
    </triangles>
   </mesh>
  </object>
 </resources>
 <build>
  <item objectid="1" transform="1 0 0 0 1 0 0 0 1 20 20 0"/>
  <item objectid="2" transform="1 0 0 0 1 0 0 0 1 236 20 0"/>
 </build>
</model>
"""


MULTIPLATE_MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <model_instance>
      <metadata key="object_id" value="1"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="11"/>
    </model_instance>
  </plate>
  <plate>
    <metadata key="plater_id" value="2"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="22"/>
    </model_instance>
  </plate>
</config>
"""


SINGLE_PLATE_MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="1">
    <metadata key="extruder" value="1"/>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <model_instance>
      <metadata key="object_id" value="1"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="11"/>
    </model_instance>
  </plate>
</config>
"""


COMPONENT_MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources>
  <object id="1" type="model">
   <mesh>
    <vertices>
     <vertex x="0" y="0" z="0"/>
     <vertex x="10" y="0" z="0"/>
     <vertex x="0" y="10" z="0"/>
    </vertices>
    <triangles>
     <triangle v1="0" v2="1" v3="2"/>
    </triangles>
   </mesh>
  </object>
  <object id="2" type="model">
   <components>
    <component objectid="1" transform="1 0 0 0 1 0 0 0 1 3 4 0"/>
   </components>
  </object>
 </resources>
 <build>
  <item objectid="2" transform="1 0 0 0 1 0 0 0 1 20 30 0"/>
 </build>
</model>
"""


COMPONENT_MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2">
    <metadata key="extruder" value="1"/>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="11"/>
    </model_instance>
  </plate>
</config>
"""


SINGLE_PLATE_A1_PROJECT = json.dumps(
    {
        "printable_area": ["0x0", "180x0", "180x180", "0x180"],
        "filament_settings_id": ["Bambu PLA Basic @BBL A1M"],
        "filament_type": ["PLA"],
        "filament_colour": ["#C12E1F"],
        "layer_height": "0.20",
        "nozzle_diameter": ["0.4"],
    }
)


PRUSA_MODEL_XML = MODEL_XML.replace(
    "<model ",
    '<model xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06" ',
).replace(
    '<triangle v1="0" v2="1" v3="2"/>',
    '<triangle v1="0" v2="1" v3="2" slic3rpe:mmu_segmentation="0 1 2"/>',
)


def _write_3mf(path: Path, files: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types/>')
        for name, payload in files.items():
            zf.writestr(name, payload)


def _reference_profile() -> Path:
    return Path(__file__).resolve().parents[1] / "profiles" / "U1 Ref - 0.20 Standard.3mf"


def _settings(reference: Path) -> BuildRequestSettings:
    return BuildRequestSettings(
        reference_profile=reference.stem,
        apply_recipe_book=False,
        clamp_speeds=True,
        preserve_color_painting=True,
    )


def test_prusaslicer_mmu_project_is_rebuilt_as_orca_project(tmp_path: Path) -> None:
    source = tmp_path / "real-layout-prusa.3mf"
    _write_3mf(
        source,
        {
            "3D/3dmodel.model": PRUSA_MODEL_XML,
            "Metadata/Slic3r_PE.config": """
layer_height = 0.20
filament_settings_id = Prusament PLA;Generic PETG
filament_type = PLA;PETG
extruder_colour = #112233;#445566
temperature = 215;240
first_layer_temperature = 220;245
bed_temperature = 60;80
first_layer_bed_temperature = 65;85
filament_diameter = 1.75;1.75
nozzle_diameter = 0.4
single_extruder_multi_material = 1
wipe_tower = 1
""",
            "Metadata/Slic3r_PE_model.config": """<?xml version="1.0" encoding="UTF-8"?>
<config><object id="1"><metadata type="object" key="extruder" value="2"/></object></config>
""",
        },
    )

    cfg, slicer = read_source_settings(source)
    assert slicer == "PrusaSlicer"
    assert cfg["filament_settings_id"] == ["Prusament PLA", "Generic PETG"]
    assert cfg["filament_colour"] == ["#112233", "#445566"]

    reference = _reference_profile()
    output = tmp_path / "converted-prusa.3mf"
    result = forge_package(
        source_path=source,
        reference_path=reference,
        output_path=output,
        settings=_settings(reference),
        rules=[],
    )

    assert result.diff.counts()["slot_remaps"] == 2
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert "Metadata/project_settings.config" in names
        assert "Metadata/model_settings.config" in names
        assert "Metadata/slice_info.config" in names
        assert "Metadata/Slic3r_PE.config" not in names
        model_xml = zf.read("3D/3dmodel.model").decode("utf-8")
        assert "slic3rpe:" not in model_xml
        assert "paint_color=" in model_xml
        project = json.loads(zf.read("Metadata/project_settings.config"))
        assert project["filament_settings_id"][:2] == ["Snapmaker PLA Matte @U1", "Generic PETG"]
        assert not any("@BBL" in value for value in project["filament_settings_id"])
        assert project["exclude_object"] == "1"


def test_cura_multiextruder_project_preserves_material_slots(tmp_path: Path) -> None:
    source = tmp_path / "real-layout-cura.3mf"
    _write_3mf(
        source,
        {
            "3D/3dmodel.model": MODEL_XML,
            "Cura/quality_changes/global.cfg": """
[general]
version = 5
[values]
layer_height = 0.16
machine_name = Ultimaker S5
machine_nozzle_size = 0.4
material_bed_temperature = 60
material_bed_temperature_layer_0 = 65
""",
            "Cura/quality_changes/extruder_0.cfg": """
[values]
material_name = Generic PLA
material_type = PLA
material_brand = Generic
material_colour = #abcdef
material_diameter = 1.75
material_print_temperature = 210
material_print_temperature_layer_0 = 215
""",
            "Cura/quality_changes/extruder_1.cfg": """
[values]
material_name = Tough PETG
material_type = PETG
material_brand = Generic
material_colour = #123456
material_diameter = 1.75
material_print_temperature = 240
material_print_temperature_layer_0 = 245
""",
        },
    )

    cfg, slicer = read_source_settings(source)
    assert slicer == "Cura"
    assert cfg["filament_settings_id"] == ["Generic PLA", "Tough PETG"]
    assert cfg["filament_type"] == ["PLA", "PETG"]
    assert cfg["nozzle_temperature"] == ["210", "240"]

    reference = _reference_profile()
    output = tmp_path / "converted-cura.3mf"
    result = forge_package(
        source_path=source,
        reference_path=reference,
        output_path=output,
        settings=_settings(reference),
        rules=[],
    )

    assert result.diff.counts()["slot_remaps"] == 2
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert not any(name.startswith("Cura/") for name in names)
        project = json.loads(zf.read("Metadata/project_settings.config"))
        assert project["filament_settings_id"][:2] == ["Snapmaker PLA Matte @U1", "Generic PETG"]
        assert not any("@BBL" in value for value in project["filament_settings_id"])
        assert project["filament_colour"][:2] == ["#abcdef", "#123456"]
        model_settings = zf.read("Metadata/model_settings.config").decode("utf-8")
        assert 'key="filament_maps" value="1 2"' in model_settings


def test_geometry_only_3mf_gets_safe_default_material_and_orca_sidecars(tmp_path: Path) -> None:
    source = tmp_path / "geometry-only.3mf"
    _write_3mf(source, {"3D/3dmodel.model": MODEL_XML})

    cfg, slicer = read_source_settings(source)
    assert slicer == "Geometry"
    assert cfg["filament_settings_id"] == ["Generic PLA"]
    assert cfg["filament_colour"] == ["#808080"]

    reference = _reference_profile()
    output = tmp_path / "converted-geometry.3mf"
    result = forge_package(
        source_path=source,
        reference_path=reference,
        output_path=output,
        settings=_settings(reference),
        rules=[],
    )

    assert result.diff.counts()["slot_remaps"] == 1
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert "Metadata/project_settings.config" in names
        assert "Metadata/model_settings.config" in names
        assert "Metadata/slice_info.config" in names
        project = json.loads(zf.read("Metadata/project_settings.config"))
        reference_settings = read_project_settings(reference)
        assert project["print_settings_id"] == reference_settings["print_settings_id"]
        assert project["filament_settings_id"] == ["Snapmaker PLA Matte @U1"]
        assert not any("@BBL" in value for value in project["filament_settings_id"])
        assert project["filament_type"] == ["PLA"]


def test_multiplate_objects_are_fitted_per_u1_plate(tmp_path: Path) -> None:
    source = tmp_path / "bambu-style-two-plate.3mf"
    _write_3mf(
        source,
        {
            "3D/3dmodel.model": MULTIPLATE_MODEL_XML,
            "Metadata/model_settings.config": MULTIPLATE_MODEL_SETTINGS,
            "Metadata/project_settings.config": json.dumps(
                {
                    "printable_area": ["0x0", "180x0", "180x180", "0x180"],
                    "filament_settings_id": ["Bambu PLA Basic @BBL A1M"],
                    "filament_type": ["PLA"],
                    "filament_colour": ["#FFFFFF"],
                    "layer_height": "0.20",
                    "nozzle_diameter": ["0.4"],
                }
            ),
        },
    )

    reference = _reference_profile()
    output = tmp_path / "converted-two-plate.3mf"
    forge_package(
        source_path=source,
        reference_path=reference,
        output_path=output,
        settings=_settings(reference),
        rules=[],
    )

    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert "Metadata/plate_1.json" in names
        assert "Metadata/plate_2.json" in names
        model_xml = zf.read("3D/3dmodel.model").decode("utf-8")
        assert 'objectid="1" transform="1 0 0 0 1 0 0 0 1 125.5 126 0"' in model_xml
        assert 'objectid="2" transform="1 0 0 0 1 0 0 0 1 431.5 126 0"' in model_xml

    scene = build_preview_scene(output)
    assert scene["stats"]["objects"] == 2
    assert scene["stats"]["triangles"] == 2
    assert [plate["id"] for plate in scene["plates"]] == [1, 2]
    assert scene["meshes"][0]["vertices"]
    assert scene["meshes"][0]["triangle_colors"]


def test_single_plate_source_bed_center_maps_to_u1_center(tmp_path: Path) -> None:
    source = tmp_path / "single-plate-a1.3mf"
    source_model = MODEL_XML.replace('transform="1 0 0 0 1 0 0 0 1 0 0 0"', 'transform="1 0 0 0 1 0 0 0 1 90 90 0"')
    _write_3mf(
        source,
        {
            "3D/3dmodel.model": source_model,
            "Metadata/model_settings.config": SINGLE_PLATE_MODEL_SETTINGS,
            "Metadata/project_settings.config": SINGLE_PLATE_A1_PROJECT,
        },
    )

    reference = _reference_profile()
    output = tmp_path / "converted-single.3mf"
    forge_package(
        source_path=source,
        reference_path=reference,
        output_path=output,
        settings=_settings(reference),
        rules=[],
    )

    with zipfile.ZipFile(output) as zf:
        model_xml = zf.read("3D/3dmodel.model").decode("utf-8")
        assert 'transform="1 0 0 0 1 0 0 0 1 135.5 136 0"' in model_xml


def test_internal_component_objects_are_rendered_and_fitted(tmp_path: Path) -> None:
    source = tmp_path / "component-wrapper.3mf"
    _write_3mf(
        source,
        {
            "3D/3dmodel.model": COMPONENT_MODEL_XML,
            "Metadata/model_settings.config": COMPONENT_MODEL_SETTINGS,
            "Metadata/project_settings.config": json.dumps(
                {
                    "printer_model": "Bambu Lab P1S",
                    "printer_settings_id": "Bambu Lab P1S 0.4 nozzle",
                    "print_settings_id": "0.20mm Standard @BBL X1C",
                    "default_print_profile": "0.20mm Standard @BBL X1C",
                    "default_filament_profile": ["Bambu PLA Basic @BBL P1S 0.4 nozzle"],
                    "print_compatible_printers": ["Bambu Lab P1S 0.4 nozzle"],
                    "upward_compatible_machine": ["Bambu Lab P1S 0.4 nozzle"],
                    "printable_area": ["0x0", "180x0", "180x180", "0x180"],
                    "filament_settings_id": ["Bambu PLA Basic @BBL P1S 0.4 nozzle"],
                    "filament_type": ["PLA"],
                    "filament_colour": ["#FFFFFF"],
                    "layer_height": "0.20",
                    "nozzle_diameter": ["0.4"],
                    "wall_filament": "0",
                    "solid_infill_filament": "0",
                    "sparse_infill_filament": "0",
                    "bottom_shell_layers": "10",
                    "raft_first_layer_expansion": "-1",
                    "tree_support_wall_count": "-1",
                }
            ),
        },
    )

    reference = _reference_profile()
    output = tmp_path / "converted-component.3mf"
    forge_package(source_path=source, reference_path=reference, output_path=output, settings=_settings(reference), rules=[])

    scene = build_preview_scene(output)
    assert scene["stats"]["objects"] == 1
    assert scene["stats"]["triangles"] == 1
    with zipfile.ZipFile(output) as zf:
        project = json.loads(zf.read("Metadata/project_settings.config"))
    assert project["printer_model"] == "Snapmaker U1"
    assert project["print_settings_id"] == "0.20 Standard @Snapmaker U1 (0.4 nozzle)"
    assert project["default_print_profile"] == "0.20 Standard @Snapmaker U1 (0.4 nozzle)"
    assert project["default_filament_profile"] == ["Snapmaker PLA"]
    assert project["print_compatible_printers"] == ["Snapmaker U1 (0.4 nozzle)"]
    assert project["upward_compatible_machine"] == []
    assert project["wall_filament"] == "1"
    assert project["solid_infill_filament"] == "1"
    assert project["sparse_infill_filament"] == "1"
    assert project["raft_first_layer_expansion"] == "2"
    assert project["tree_support_wall_count"] == "0"
    assert "bottom_shell_layers" in project["different_settings_to_system"][0]


def test_embedded_thumbnail_is_preferred_over_render(tmp_path: Path) -> None:
    source = tmp_path / "thumbnail-priority.3mf"
    embedded_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax4ZVQAAAAASUVORK5CYII="
    )
    _write_3mf(
        source,
        {
            "3D/3dmodel.model": MODEL_XML,
            "Metadata/project_settings.config": json.dumps(
                {
                    "printable_area": ["0x0", "180x0", "180x180", "0x180"],
                    "filament_settings_id": ["Generic PLA"],
                    "filament_type": ["PLA"],
                    "filament_colour": ["#FFFFFF"],
                    "layer_height": "0.20",
                }
            ),
            "Auxiliaries/.thumbnails/thumbnail_3mf.png": embedded_png,
        },
    )

    assert (_thumbnail_data_url(source) or "").startswith("data:image/png;base64,")
