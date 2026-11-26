"""Compact M27 artistic-intent editor for the Generator workspace.

The widget authors a CompositionBrief and declarative mutation permissions. It
contains no renderer or project state; MainWindow compiles the brief against the
current GenerationConfig before generation or when applying it to a loaded project.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reawarp.composition.brief import (
    BRIEF_ROLES,
    ENDING_MODES,
    AnchorSpec,
    CompositionBrief,
    ContrastTarget,
    EndingIntent,
    MaterialIdentity,
    PitchWorld,
    TempoFormPolicy,
    quick_mutation_contracts,
    source_families_from_config,
)
from reawarp.composition.brief import FIELD_SCOPE


MATERIAL_FUNCTIONS = {"A": "anchor", "B": "response", "C": "destabiliser"}
ROLE_ORDER = (
    "kick", "snare", "hat", "break", "melody", "texture", "ambience", "percussion",
)
MUTATION_LABELS = {
    "arrangement_density": "Arrangement density",
    "arrangement_instability": "Instability",
    "rhythmic_syncopation": "Syncopation",
    "melodic_activity": "Melodic activity",
    "melody_register_semitones": "Melody register",
    "tonal_brightness": "Tonal brightness",
    "spatial_intent": "Spatial intent",
    "composition_energy": "Composition energy",
    "composition_variation": "Structural variation",
    "complexity": "Complexity",
    "break_density": "Break density",
    "break_variation": "Break variation",
    "drum_change_intensity": "Drum evolution",
    "ambience_level": "Ambience level",
    "bpm": "Tempo / BPM",
    "duration": "Duration",
    "structure": "Formal trajectory",
    "composition_flow": "Structure flow",
}


class CompositionIntentEditor(QGroupBox):
    """Author a versioned brief and explicit GenerationConfig mutation contracts."""

    applyRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("M27  /  ARTISTIC INTENT + MUTATION CONTRACTS", parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)

        intro = QLabel(
            "Describe what should remain recognisable, which materials belong together, "
            "and which generator dimensions may change. Nothing is randomised unless "
            "bounded exploration is explicitly enabled."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        form_group = QGroupBox("COMPOSITION BRIEF")
        form = QFormLayout(form_group)
        self.brief_id = QLineEdit("composition-01")
        self.brief_id.setPlaceholderText("Stable brief ID")
        form.addRow("Brief ID", self.brief_id)
        self.artistic_question = QLineEdit()
        self.artistic_question.setPlaceholderText("What tension or question holds this piece together?")
        form.addRow("Artistic question", self.artistic_question)
        self.listening_mode = QLineEdit()
        self.listening_mode.setPlaceholderText("e.g. close listening, movement, spatial study")
        form.addRow("Listening mode", self.listening_mode)

        materials_group = QGroupBox("MATERIAL VOCABULARY  /  A · B · C")
        materials_layout = QFormLayout(materials_group)
        self.material_labels: dict[str, QLineEdit] = {}
        self.material_roles: dict[str, QComboBox] = {}
        for material_id, label in (("A", "Anchor"), ("B", "Response"), ("C", "Destabiliser")):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            name = QLineEdit()
            name.setPlaceholderText(f"{label} material (optional)")
            role = self._role_combo(allow_unassigned=True)
            self.material_labels[material_id] = name
            self.material_roles[material_id] = role
            row_layout.addWidget(name, 2)
            row_layout.addWidget(role, 1)
            materials_layout.addRow(material_id, row)
        form.addRow(materials_group)

        anchor_group = QGroupBox("ANCHOR")
        anchor_form = QFormLayout(anchor_group)
        self.anchor_kind = QComboBox()
        for value in ("none", "pulse", "motif", "sound_object", "role", "spatial_feature"):
            self.anchor_kind.addItem(value.replace("_", " ").title(), value)
        anchor_form.addRow("Anchor kind", self.anchor_kind)
        self.anchor_material = QComboBox()
        self.anchor_material.addItem("Unassigned", "")
        for material_id in ("A", "B", "C"):
            self.anchor_material.addItem(f"Material {material_id}", material_id)
        anchor_form.addRow("Material", self.anchor_material)
        self.anchor_role = self._role_combo(allow_unassigned=True)
        anchor_form.addRow("Role", self.anchor_role)
        self.anchor_description = QLineEdit()
        self.anchor_description.setPlaceholderText("What should remain recognisable?")
        anchor_form.addRow("Description", self.anchor_description)
        form.addRow(anchor_group)

        contrast_group = QGroupBox("CONTRAST + ENDING")
        contrast_form = QFormLayout(contrast_group)
        self.contrast_label = QLineEdit()
        self.contrast_label.setPlaceholderText("Optional contrast to preserve or develop")
        contrast_form.addRow("Target contrast", self.contrast_label)
        self.contrast_dimensions = QLineEdit()
        self.contrast_dimensions.setPlaceholderText("e.g. rhythm, timbre, register")
        contrast_form.addRow("Dimensions", self.contrast_dimensions)
        self.ending_mode = QComboBox()
        for value in sorted(ENDING_MODES):
            self.ending_mode.addItem(value.replace("_", " ").title(), value)
        contrast_form.addRow("Ending behaviour", self.ending_mode)
        self.ending_preserve = QComboBox()
        self.ending_preserve.addItem("No named material", "")
        for material_id in ("A", "B", "C"):
            self.ending_preserve.addItem(f"Preserve material {material_id}", material_id)
        contrast_form.addRow("Retain at ending", self.ending_preserve)
        form.addRow(contrast_group)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional authorship / production notes")
        form.addRow("Notes", self.notes)
        root.addWidget(form_group)

        pitch_group = QGroupBox("PITCH WORLD")
        pitch_form = QFormLayout(pitch_group)
        from reawarp.mathematics.theory import ROOT_NAMES, SCALE_STEPS

        self.pitch_scale = QComboBox()
        self.pitch_scale.addItems(list(SCALE_STEPS))
        self.pitch_root = QComboBox()
        for index, name in enumerate(ROOT_NAMES):
            self.pitch_root.addItem(name, index)
        pitch_form.addRow("Scale", self.pitch_scale)
        pitch_form.addRow("Root", self.pitch_root)
        self.tuning_id = QLineEdit("12tet")
        self.tuning_id.setToolTip(
            "Stored as intent metadata. The current GenerationConfig renderer maps scale and root only."
        )
        pitch_form.addRow("Tuning identity", self.tuning_id)
        root.addWidget(pitch_group)

        policy_group = QGroupBox("TEMPO / FORM POLICY")
        policy_form = QFormLayout(policy_group)
        self.bpm_min = self._number(60.0, 220.0, 60.0, 1)
        self.bpm_max = self._number(60.0, 220.0, 220.0, 1)
        bpm_row = QWidget()
        bpm_layout = QHBoxLayout(bpm_row)
        bpm_layout.setContentsMargins(0, 0, 0, 0)
        bpm_layout.addWidget(QLabel("min"))
        bpm_layout.addWidget(self.bpm_min)
        bpm_layout.addWidget(QLabel("max"))
        bpm_layout.addWidget(self.bpm_max)
        policy_form.addRow("Exploration bounds / BPM", bpm_row)
        self.duration_min = self._number(5.0, 180.0, 5.0, 1)
        self.duration_max = self._number(5.0, 180.0, 180.0, 1)
        duration_row = QWidget()
        duration_layout = QHBoxLayout(duration_row)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.addWidget(QLabel("min"))
        duration_layout.addWidget(self.duration_min)
        duration_layout.addWidget(QLabel("max"))
        duration_layout.addWidget(self.duration_max)
        policy_form.addRow("Exploration bounds / sec", duration_row)
        policy_note = QLabel(
            "Tempo, duration and formal structure are preserved unless the matching "
            "field is selected below; the declared bounds then become active."
        )
        policy_note.setWordWrap(True)
        policy_note.setObjectName("muted")
        policy_form.addRow(policy_note)
        root.addWidget(policy_group)

        mutation_group = QGroupBox("MUTATION CONTRACTS  /  ALLOWED TO CHANGE")
        mutation_layout = QVBoxLayout(mutation_group)
        mutation_note = QLabel(
            "Selecting a field declares permission, not an automatic edit. The field's "
            "scope, valid domain and deterministic seed are recorded in the brief."
        )
        mutation_note.setWordWrap(True)
        mutation_note.setObjectName("muted")
        mutation_layout.addWidget(mutation_note)
        grid = QGridLayout()
        self.mutation_checks: dict[str, QCheckBox] = {}
        names = sorted(FIELD_SCOPE, key=lambda item: (FIELD_SCOPE[item], item))
        for index, field_name in enumerate(names):
            label = MUTATION_LABELS.get(field_name, field_name.replace("_", " ").title())
            checkbox = QCheckBox(label)
            checkbox.setToolTip(
                f"{FIELD_SCOPE[field_name].title()} scope · {field_name}"
            )
            self.mutation_checks[field_name] = checkbox
            grid.addWidget(checkbox, index // 3, index % 3)
        mutation_layout.addLayout(grid)
        self.bounded_exploration = QCheckBox(
            "APPLY THESE MUTATIONS ON THE NEXT GENERATION"
        )
        self.bounded_exploration.setToolTip(
            "When enabled, only selected contract fields are sampled. The seed and all "
            "unselected settings remain unchanged. The generated values are shown in Generator."
        )
        mutation_layout.addWidget(self.bounded_exploration)
        root.addWidget(mutation_group)

        footer = QHBoxLayout()
        self.status = QLabel("Brief is optional. Legacy projects are never assigned an inferred brief.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        footer.addWidget(self.status, 1)
        self.apply_button = QPushButton("APPLY BRIEF TO CURRENT PROJECT")
        self.apply_button.clicked.connect(self.applyRequested.emit)
        footer.addWidget(self.apply_button)
        root.addLayout(footer)

        self._loaded_contracts = ()
        self._loaded_contract_fields: frozenset[str] = frozenset()

    @staticmethod
    def _number(minimum: float, maximum: float, value: float, decimals: int) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        return control

    @staticmethod
    def _role_combo(*, allow_unassigned: bool) -> QComboBox:
        combo = QComboBox()
        if allow_unassigned:
            combo.addItem("Unassigned", "")
        for role in ROLE_ORDER:
            if role in BRIEF_ROLES:
                combo.addItem(role.title(), role)
        return combo

    def selected_mutation_fields(self) -> tuple[str, ...]:
        return tuple(
            field_name for field_name, checkbox in self.mutation_checks.items()
            if checkbox.isChecked()
        )

    def exploration_enabled(self) -> bool:
        return self.bounded_exploration.isChecked()

    def has_user_content(self) -> bool:
        return bool(
            self.artistic_question.text().strip()
            or self.listening_mode.text().strip()
            or any(field.text().strip() for field in self.material_labels.values())
            or self.anchor_kind.currentData() != "none"
            or self.contrast_label.text().strip()
            or self.ending_mode.currentData() != "unspecified"
            or self.notes.text().strip()
            or self.selected_mutation_fields()
        )

    def build_brief(self, config: Any) -> CompositionBrief:
        """Build and validate a brief against the current source/config snapshot."""
        source_families = source_families_from_config(config)
        family_by_role = {item.role: item for item in source_families}
        materials = []
        for material_id in ("A", "B", "C"):
            label = self.material_labels[material_id].text().strip()
            if not label:
                continue
            role = str(self.material_roles[material_id].currentData() or "")
            family = family_by_role.get(role)
            source_ids = tuple(
                asset.reference_id for asset in family.assets
            ) if family is not None else ()
            materials.append(MaterialIdentity(
                material_id=material_id,
                label=label,
                function=MATERIAL_FUNCTIONS[material_id],
                role=role,
                source_asset_ids=source_ids,
            ))

        anchor_kind = str(self.anchor_kind.currentData())
        if anchor_kind == "none":
            anchor = AnchorSpec()
        else:
            material_id = str(self.anchor_material.currentData() or "") or None
            role = str(self.anchor_role.currentData() or "") or None
            description = self.anchor_description.text().strip()
            if not (material_id or role or description):
                description = f"Preserve the identity of the {anchor_kind.replace('_', ' ')} anchor."
            anchor = AnchorSpec(
                kind=anchor_kind, material_id=material_id,
                role=role, description=description,
            )

        ending_mode = str(self.ending_mode.currentData())
        preserve_id = str(self.ending_preserve.currentData() or "")
        ending = EndingIntent(
            mode=ending_mode,
            preserve_material_ids=(preserve_id,) if preserve_id else (),
        )
        contrast = self.contrast_label.text().strip()
        contrasts = ()
        if contrast:
            dimensions = tuple(
                item.strip() for item in self.contrast_dimensions.text().split(",")
                if item.strip()
            )
            contrasts = (ContrastTarget(
                label=contrast,
                material_ids=tuple(item.material_id for item in materials),
                dimensions=dimensions,
            ),)

        fields = self.selected_mutation_fields()
        if self.exploration_enabled() and not fields:
            raise ValueError(
                "Bounded exploration is enabled, but no mutable GenerationConfig fields are selected."
            )
        if set(fields) == set(self._loaded_contract_fields) and self._loaded_contracts:
            contracts = self._loaded_contracts
        else:
            contracts = quick_mutation_contracts(fields)

        selected = set(fields)
        policy = TempoFormPolicy(
            bpm_mode="explore" if "bpm" in selected else "preserve",
            duration_mode="explore" if "duration" in selected else "preserve",
            form_mode=(
                "explore" if {"structure", "composition_flow"} & selected else "preserve"
            ),
            bpm_bounds=(self.bpm_min.value(), self.bpm_max.value()),
            duration_bounds=(self.duration_min.value(), self.duration_max.value()),
        )
        scale = str(self.pitch_scale.currentText())
        root = int(self.pitch_root.currentData())
        return CompositionBrief(
            brief_id=self.brief_id.text().strip() or "composition-brief",
            artistic_question=self.artistic_question.text().strip(),
            listening_mode=self.listening_mode.text().strip(),
            materials=tuple(materials),
            anchor=anchor,
            pitch_world=PitchWorld(
                scale=scale, root=root, tuning_id=self.tuning_id.text().strip() or "12tet",
            ),
            source_families=source_families,
            target_contrasts=contrasts,
            ending_intent=ending,
            mutation_contracts=contracts,
            tempo_form_policy=policy,
            notes=self.notes.text().strip(),
        )

    def set_brief(
        self, brief: CompositionBrief, *, exploration_enabled: bool = False
    ) -> None:
        """Load an authored brief without inventing fields or changing project state."""
        self.brief_id.setText(brief.brief_id)
        self.artistic_question.setText(brief.artistic_question)
        self.listening_mode.setText(brief.listening_mode)
        by_id = {item.material_id: item for item in brief.materials}
        for material_id in ("A", "B", "C"):
            material = by_id.get(material_id)
            self.material_labels[material_id].setText(material.label if material else "")
            self.material_roles[material_id].setCurrentIndex(
                max(0, self.material_roles[material_id].findData(material.role if material else ""))
            )
        self.anchor_kind.setCurrentIndex(
            max(0, self.anchor_kind.findData(brief.anchor.kind))
        )
        self.anchor_material.setCurrentIndex(
            max(0, self.anchor_material.findData(brief.anchor.material_id or ""))
        )
        self.anchor_role.setCurrentIndex(
            max(0, self.anchor_role.findData(brief.anchor.role or ""))
        )
        self.anchor_description.setText(brief.anchor.description)
        self.contrast_label.setText(
            brief.target_contrasts[0].label if brief.target_contrasts else ""
        )
        self.contrast_dimensions.setText(
            ", ".join(brief.target_contrasts[0].dimensions)
            if brief.target_contrasts else ""
        )
        self.ending_mode.setCurrentIndex(
            max(0, self.ending_mode.findData(brief.ending_intent.mode))
        )
        preserve = brief.ending_intent.preserve_material_ids[0] if brief.ending_intent.preserve_material_ids else ""
        self.ending_preserve.setCurrentIndex(max(0, self.ending_preserve.findData(preserve)))
        self.notes.setText(brief.notes)
        self.pitch_scale.setCurrentText(brief.pitch_world.scale)
        self.pitch_root.setCurrentIndex(
            max(0, self.pitch_root.findData(brief.pitch_world.root))
        )
        self.tuning_id.setText(brief.pitch_world.tuning_id)
        for checkbox in self.mutation_checks.values():
            checkbox.setChecked(False)
        fields = {
            field_name for contract in brief.mutation_contracts
            for field_name in contract.mutable_fields
        }
        for field_name in fields:
            checkbox = self.mutation_checks.get(field_name)
            if checkbox is not None:
                checkbox.setChecked(True)
        self._loaded_contracts = tuple(brief.mutation_contracts)
        self._loaded_contract_fields = frozenset(fields)
        self.bpm_min.setValue(brief.tempo_form_policy.bpm_bounds[0])
        self.bpm_max.setValue(brief.tempo_form_policy.bpm_bounds[1])
        self.duration_min.setValue(brief.tempo_form_policy.duration_bounds[0])
        self.duration_max.setValue(brief.tempo_form_policy.duration_bounds[1])
        self.bounded_exploration.setChecked(bool(exploration_enabled))
        self.set_status("Loaded the saved M27 brief and mutation permissions.")

    def clear(self) -> None:
        self.set_brief(CompositionBrief(brief_id="composition-01"))
        self.artistic_question.clear()
        self.listening_mode.clear()
        for field in self.mutation_checks.values():
            field.setChecked(False)
        self.bounded_exploration.setChecked(False)
        self.set_status("No authored M27 brief is attached to this project.")

    def set_status(self, message: str) -> None:
        self.status.setText(str(message))
