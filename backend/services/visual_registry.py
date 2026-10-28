"""Typed visual selection and deterministic, non-executing visual timelines."""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

from backend.schemas import (
    CauseEffectData,
    CodeExecutionData,
    CycleData,
    EquationStepsData,
    FractionModelData,
    NumberLineData,
    Scene,
    VisualType,
)


PROGRAMMING_TOPIC = re.compile(
    r"\b(python|javascript|typescript|program(?:ming)?|code|algorithm|for[- ]?loops?|while loops?)\b",
    re.IGNORECASE,
)
FRACTION_TOPIC = re.compile(
    r"\b(fractions?|ratios?|percentages?|percent|parts of a whole)\b",
    re.IGNORECASE,
)
PHOTOSYNTHESIS_TOPIC = re.compile(r"photosynth", re.IGNORECASE)
EQUATION_TOPIC = re.compile(r"\b(solve|solving|linear equation|equation|isolate [a-z])\b", re.IGNORECASE)
CYCLE_TOPIC = re.compile(
    r"\b(water cycle|cell cycle|carbon cycle|nitrogen cycle|rock cycle|life cycle of [a-z]+)\b",
    re.IGNORECASE,
)
RAG_TOPIC = re.compile(r"\b(rag|retrieval[- ]augmented generation)\b", re.IGNORECASE)
DEEP_LEARNING_TOPIC = re.compile(r"\bdeep learning\b|\bdeep neural networks?\b", re.IGNORECASE)
NEURAL_NETWORK_TOPIC = re.compile(r"\bneural networks?\b", re.IGNORECASE)
VECTOR_RETRIEVAL_TOPIC = re.compile(
    r"\b(vector database|vector search|embeddings?|semantic search)\b", re.IGNORECASE
)
API_TOPIC = re.compile(
    r"\b(api|rest api|application programming interface|http request)\b", re.IGNORECASE
)
LLM_TOPIC = re.compile(r"\b(llm|large language models?|transformers?)\b", re.IGNORECASE)
ML_TOPIC = re.compile(
    r"\b(machine learning|supervised learning|model training|train(?:ing)? a model|\bml\b)\b",
    re.IGNORECASE,
)
AI_TOPIC = re.compile(r"\b(ai|artificial intelligence)\b", re.IGNORECASE)
FLOW_KEYS = ("input", "process", "step_2", "step_3", "output")
VISUAL_HINTS = {
    "title_card": "title_card",
    "concept": "concept_diagram",
    "concept_diagram": "concept_diagram",
    "diagram": "concept_diagram",
    "flow": "process_flow",
    "flowchart": "process_flow",
    "process_flow": "process_flow",
    "code": "code",
    "code_execution": "code_execution",
    "fraction_model": "fraction_model",
    "cause_effect": "cause_effect",
    "number_line": "number_line",
    "equation_steps": "equation_steps",
    "cycle": "cycle",
}


def is_programming_topic(topic: str) -> bool:
    return bool(PROGRAMMING_TOPIC.search(topic))


def is_fraction_topic(topic: str) -> bool:
    return bool(
        FRACTION_TOPIC.search(topic)
        or re.search(r"(?<!\d)[1-8]\s*/\s*[2-8](?!\d)", topic)
    )


def _engineering_strategy(topic: str) -> tuple[str, dict[str, str] | CycleData] | None:
    """Select a bounded, concrete demonstration for common AI/software topics."""
    if RAG_TOPIC.search(topic):
        return "process_flow", {
            "input": "User asks a question",
            "process": "Retrieve matching document chunks",
            "step_2": "Add retrieved context to the prompt",
            "output": "LLM writes a grounded answer",
        }
    if VECTOR_RETRIEVAL_TOPIC.search(topic):
        return "process_flow", {
            "input": "Turn the query into an embedding",
            "process": "Compare it with stored vectors",
            "step_2": "Select the nearest matching chunks",
            "output": "Return relevant source text",
        }
    if API_TOPIC.search(topic):
        return "process_flow", {
            "input": "Client sends an HTTP request",
            "process": "API checks the route and inputs",
            "step_2": "Service performs the requested operation",
            "output": "Server returns a response",
        }
    if DEEP_LEARNING_TOPIC.search(topic) or NEURAL_NETWORK_TOPIC.search(topic):
        if re.search(r"\b(train|training|fit|learn from examples)\b", topic, re.I):
            return "cycle", CycleData(
                center_label="neural network training",
                stages=[
                    "training example",
                    "forward prediction",
                    "measure prediction error",
                    "backpropagate gradients",
                    "update connection weights",
                ],
            )
        if DEEP_LEARNING_TOPIC.search(topic):
            return "process_flow", {
                "input": "Input example",
                "process": "Early layer detects patterns",
                "step_2": "Later layers combine features",
                "output": "Model prediction",
            }
        return "process_flow", {
            "input": "Input values",
            "process": "Weighted connections",
            "step_2": "Sum and apply activation",
            "output": "Signal to next layer",
        }
    if ML_TOPIC.search(topic):
        if re.search(r"\b(train|training|fit|learn from examples)\b", topic, re.I):
            return "cycle", CycleData(
                center_label="ML training loop",
                stages=[
                    "training examples",
                    "model makes predictions",
                    "measure prediction error",
                    "update model weights",
                ],
            )
        return "process_flow", {
            "input": "Training examples",
            "process": "Model learns patterns from examples",
            "step_2": "New data arrives",
            "output": "Model predicts a result",
        }
    if LLM_TOPIC.search(topic):
        return "process_flow", {
            "input": "Text is split into tokens",
            "process": "Transformer layers combine token context",
            "step_2": "Model predicts the next token",
            "output": "Tokens build the response",
        }
    if AI_TOPIC.search(topic):
        return "process_flow", {
            "input": "Provide data or a goal",
            "process": "AI model finds useful patterns",
            "output": "Model predicts or generates an output",
        }
    return None


def _short_label(value: object, limit: int = 72) -> str:
    text = " ".join(str(value).split())
    text = re.sub(r"^(?:visual|diagram|flowchart|caption)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"^(?:a\s+)?visual\s+(?:of|showing)\s+", "", text, flags=re.I)
    text = re.sub(
        r"^(?:a|an)\s+(?:simple\s+)?(?:diagram|flowchart)\s+(?:showing\s+)?",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"^(?:and|or)\s+", "", text, flags=re.I)
    text = re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.I)
    text = text.strip(" .,:;–—-")
    if len(text) > limit:
        clipped = text[: limit - 1].rsplit(" ", 1)[0]
        text = (clipped or text[: limit - 1]) + "…"
    return text


def _split_labels(value: object, *, maximum: int = 5) -> list[str]:
    """Extract a few short display labels from legacy planner output."""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(" ".join(line.split()) for line in text.splitlines()).strip()
    text = text[:320]
    text = re.sub(r"^(?:the\s+)?(?:steps?\s+of|process\s+of)\s+", "", text, flags=re.I)
    text = re.sub(r",\s*(?:and|or)\s+", ", ", text, flags=re.I)
    if re.search(r"(?:->|→|⇒|=>|\n|;|\|)", text):
        parts = re.split(r"\s*(?:->|→|⇒|=>|\n|;|\|)\s*", text)
    elif "," in text or re.search(r"\band\b", text, flags=re.I):
        parts = re.split(r"\s*,\s*|\s+and\s+", text, flags=re.I)
    else:
        return []
    labels = []
    for part in parts:
        label = re.sub(r"^\s*(?:step\s*)?\d+[.)\-:]?\s*", "", part, flags=re.I)
        label = re.sub(r"\([^)]*\)", "", label)
        if not labels and ":" in label and len(label.split(":", 1)[0].split()) <= 3:
            label = label.split(":", 1)[1]
        label = _short_label(label, 64)
        if label and label.lower() not in {item.lower() for item in labels}:
            labels.append(label)
    return labels[:maximum]


def _ordered_flow_data(data: dict[str, str], scene: Scene) -> dict[str, str] | None:
    explicit = {
        key: _short_label(data[key])
        for key in FLOW_KEYS
        if key in data and _short_label(data[key])
    }
    if len(explicit) >= 2:
        return explicit

    for key in (
        "steps",
        "process_flow",
        "flow",
        "diagram",
        "description",
        "summary",
        "caption",
    ):
        if key in data:
            labels = _split_labels(data[key])
            if len(labels) >= 2:
                break
    else:
        labels = []

    # Some small local models describe a flow as prose instead of structured
    # fields. Only promote clear ordered transitions; otherwise use the
    # validated concept-diagram fallback below.
    if len(labels) < 2:
        stages = re.split(r"(?i)\b(?:first|then|next|finally)\b", scene.narration)
        labels = [_short_label(item, 64) for item in stages if _short_label(item, 64)]
        labels = labels[:5] if len(labels) >= 3 else []
    if len(labels) < 2:
        return None

    keys_by_count = {
        2: ("input", "output"),
        3: ("input", "process", "output"),
        4: ("input", "process", "step_2", "output"),
        5: FLOW_KEYS,
    }
    keys = keys_by_count[min(len(labels), 5)]
    return {key: value for key, value in zip(keys, labels, strict=True)}


def _concept_diagram_data(
    data: dict[str, str], topic: str, scene: Scene
) -> dict[str, str]:
    aliases = {
        "left": ("left", "input", "source", "concept", "topic", "starting_idea"),
        "relationship": ("relationship", "mechanism", "process", "change", "relation"),
        "right": ("right", "output", "result", "outcome", "destination"),
    }
    normalized: dict[str, str] = {}
    for target, candidates in aliases.items():
        for key in candidates:
            if data.get(key, "").strip():
                normalized[target] = _short_label(data[key])
                break

    if "left" not in normalized:
        normalized["left"] = _short_label(topic)
    if "relationship" not in normalized:
        normalized["relationship"] = "key mechanism"
    if "right" not in normalized:
        candidate = scene.caption or scene.narration
        normalized["right"] = _short_label(candidate)
    return normalized


def _split_entities(value: str) -> list[str]:
    parts = re.split(r"\s*,\s*|\s+and\s+|\s*\+\s*", value, flags=re.I)
    return [_short_label(part, 48) for part in parts if _short_label(part, 48)]


def _cause_effect_data(data: dict[str, str]) -> CauseEffectData | None:
    input_text = data.get("inputs") or data.get("input") or data.get("causes") or ""
    output_text = data.get("outputs") or data.get("output") or data.get("results") or ""
    mechanism = data.get("mechanism") or data.get("process") or data.get("relationship") or ""
    inputs = _split_entities(input_text)
    outputs = _split_entities(output_text)
    if len(inputs) < 2 or not outputs or not mechanism:
        return None
    try:
        return CauseEffectData.model_validate(
            {
                "inputs": inputs[:3],
                "mechanism": _short_label(mechanism, 48),
                "outputs": outputs[:2],
            },
            strict=True,
        )
    except ValueError:
        return None


def _fraction_data(topic: str, scene: Scene, data: dict[str, str]) -> FractionModelData | None:
    if scene.fraction_data is not None:
        return scene.fraction_data
    if not is_fraction_topic(topic):
        return None
    if data.get("numerator", "").isdigit() and data.get("denominator", "").isdigit():
        try:
            return FractionModelData.model_validate(
                {
                    "numerator": int(data["numerator"]),
                    "denominator": int(data["denominator"]),
                },
                strict=True,
            )
        except ValueError:
            pass
    candidates = [topic, scene.title, scene.narration, scene.caption, *data.values()]
    for candidate in candidates:
        match = re.search(r"(?<!\d)([1-8])\s*/\s*([2-8])(?!\d)", candidate)
        if match:
            try:
                return FractionModelData.model_validate(
                    {"numerator": int(match.group(1)), "denominator": int(match.group(2))},
                    strict=True,
                )
            except ValueError:
                continue
    return None


def _number_line_data(topic: str, scene: Scene, data: dict[str, str]) -> NumberLineData | None:
    if scene.number_line_data is not None:
        return scene.number_line_data

    start_text = data.get("start_value") or data.get("start")
    jumps_text = data.get("jumps") or data.get("steps")
    if start_text is not None and jumps_text is not None:
        try:
            start = int(start_text.strip())
            jump_parts = re.split(r"\s*(?:\||;|,|\bthen\b)\s*", jumps_text, flags=re.I)
            jumps = []
            for part in jump_parts:
                numbers = re.findall(r"[+-]?\d+", part)
                if numbers:
                    jumps.append(int(numbers[-1]))
            if not jumps:
                raise ValueError("number-line jumps could not be parsed")
            labels_text = data.get("operation_labels") or data.get("operations") or ""
            labels = [part.strip() for part in re.split(r"\s*(?:\||;|,)\s*", labels_text) if part.strip()]
            if len(labels) != len(jumps):
                labels = [f"{'add' if jump > 0 else 'subtract'} {abs(jump)}" for jump in jumps]
            result_text = data.get("result")
            result = int(result_text.strip()) if result_text else start + sum(jumps)
            return NumberLineData.model_validate(
                {"start_value": start, "jumps": jumps, "operation_labels": labels, "result": result},
                strict=True,
            )
        except (ValueError, TypeError):
            pass

    # Parse a single integer operation directly; arithmetic is explicit and
    # bounded, and no model-provided expression is evaluated as code.
    candidates = [topic, scene.title, scene.caption, *data.values()]
    for candidate in candidates:
        match = re.search(
            r"(?<![\w.])(-?\d{1,2})\s*([+-])\s*(-?\d{1,2})(?:\s*=\s*(-?\d{1,2}))?(?![\w.])",
            candidate,
        )
        if not match:
            continue
        start, operator, operand = int(match.group(1)), match.group(2), int(match.group(3))
        jump = operand if operator == "+" else -operand
        result = start + jump
        supplied = int(match.group(4)) if match.group(4) is not None else result
        try:
            return NumberLineData.model_validate(
                {
                    "start_value": start,
                    "jumps": [jump],
                    "operation_labels": [f"{'add' if jump > 0 else 'subtract'} {abs(jump)}"],
                    "result": supplied,
                },
                strict=True,
            )
        except ValueError:
            return None
    return None


def _equation_steps_data(
    topic: str, scene: Scene, data: dict[str, str]
) -> EquationStepsData | None:
    if scene.equation_steps_data is not None:
        return scene.equation_steps_data

    equations_text = data.get("equations") or data.get("equation_steps")
    if equations_text:
        equations = [
            _short_label(part, 64)
            for part in re.split(r"\s*(?:->|→|⇒|=>|\n|;)\s*", equations_text)
            if _short_label(part, 64)
        ]
        operations_text = data.get("operations") or data.get("transformations") or ""
        operations = [
            _short_label(part, 48)
            for part in re.split(r"\s*(?:\||;|\n)\s*", operations_text)
            if _short_label(part, 48)
        ]
        if len(equations) >= 2:
            if len(operations) != len(equations) - 1:
                operations = ["apply the same operation to both sides"] * (len(equations) - 1)
            try:
                return EquationStepsData.model_validate(
                    {"equations": equations[:5], "operations": operations[:4]}, strict=True
                )
            except ValueError:
                pass

    # Support the common one-variable form ax +/- b = c as a safe, exact
    # worked transformation. More complex equations remain on a diagram/flow.
    candidates = [topic, scene.title, *data.values()]
    for candidate in candidates:
        match = re.search(
            r"(?<![A-Za-z0-9])([+-]?\d*)\s*([A-Za-z])\s*([+-]\s*\d+)?\s*=\s*([+-]?\s*\d+)(?!\d)",
            candidate,
            re.IGNORECASE,
        )
        if not match:
            continue
        raw_coefficient = match.group(1).replace(" ", "")
        variable = match.group(2)
        coefficient = -1 if raw_coefficient == "-" else 1 if raw_coefficient in {"", "+"} else int(raw_coefficient)
        offset = int(match.group(3).replace(" ", "")) if match.group(3) else 0
        right = int(match.group(4).replace(" ", ""))
        if coefficient == 0:
            continue
        equations = [match.group(0).strip()]
        operations: list[str] = []
        reduced_right = right
        if offset:
            reduced_right = right - offset
            operation = "subtract" if offset > 0 else "add"
            coefficient_label = variable if coefficient == 1 else f"-{variable}" if coefficient == -1 else f"{coefficient}{variable}"
            equations.append(f"{coefficient_label} = {reduced_right}")
            operations.append(f"{operation} {abs(offset)} from both sides")
        solution = Fraction(reduced_right, coefficient)
        if coefficient != 1:
            equations.append(f"{variable} = {solution.numerator}" if solution.denominator == 1 else f"{variable} = {solution.numerator}/{solution.denominator}")
            operations.append(f"divide both sides by {coefficient}")
        if len(equations) >= 2:
            try:
                return EquationStepsData.model_validate(
                    {"equations": equations, "operations": operations}, strict=True
                )
            except ValueError:
                return None
    return None


def _cycle_data(topic: str, scene: Scene, data: dict[str, str]) -> CycleData | None:
    if scene.cycle_data is not None:
        return scene.cycle_data
    center = data.get("center_label") or data.get("cycle") or _short_label(topic, 40)
    stages_text = data.get("stages") or data.get("cycle_stages") or data.get("steps") or ""
    stages = _split_labels(stages_text, maximum=6) if stages_text else []
    if len(stages) >= 3:
        try:
            return CycleData.model_validate(
                {"center_label": _short_label(center, 40), "stages": stages}, strict=True
            )
        except ValueError:
            stages = []
    if len(stages) < 3:
        lowered = topic.casefold()
        curated = {
            "water cycle": ["evaporation", "condensation", "precipitation", "collection"],
            "cell cycle": ["cell growth", "DNA replication", "cell preparation", "cell division"],
            "carbon cycle": ["atmospheric CO2", "plant uptake", "food-web transfer", "decomposition"],
            "nitrogen cycle": ["nitrogen fixation", "plant uptake", "animal transfer", "decomposition"],
            "rock cycle": ["magma cools", "igneous rock", "sediment forms", "metamorphic rock", "melts back to magma"],
            "life cycle of a butterfly": ["egg", "caterpillar", "chrysalis", "adult butterfly"],
        }
        for name, candidate_stages in curated.items():
            if name in lowered:
                stages = candidate_stages
                center = name.title()
                break
    if len(stages) < 3:
        return None
    try:
        return CycleData.model_validate(
            {"center_label": _short_label(center, 40), "stages": stages[:6]}, strict=True
        )
    except ValueError:
        return None


def _with_visual(
    scene: Scene,
    *,
    visual_type: VisualType,
    visual_data: dict[str, str],
    execution_data: CodeExecutionData | None = None,
    fraction_data: FractionModelData | None = None,
    cause_effect_data: CauseEffectData | None = None,
    number_line_data: NumberLineData | None = None,
    equation_steps_data: EquationStepsData | None = None,
    cycle_data: CycleData | None = None,
    title: str | None = None,
) -> Scene:
    return scene.model_copy(
        update={
            "title": title or scene.title,
            "visual_type": visual_type,
            "visual_data": visual_data,
            "execution_data": execution_data,
            "fraction_data": fraction_data,
            "cause_effect_data": cause_effect_data,
            "number_line_data": number_line_data,
            "equation_steps_data": equation_steps_data,
            "cycle_data": cycle_data,
        }
    )


def select_scene_visual_type(
    topic: str, scene: Scene, *, scene_index: int | None = None
) -> Scene:
    """Normalize model-selected visuals into complete, project-owned render data."""
    data = dict(scene.visual_data)
    embedded_hint = VISUAL_HINTS.get(data.pop("visual_type", "").strip().lower())
    if scene_index == 0:
        subtitle = data.get("subtitle") or _short_label(scene.caption or scene.narration)
        title = scene.title
        if title.strip().lower().replace("_", " ") in {"title card", "opening", "intro"}:
            title = _short_label(topic, 100)
        return _with_visual(
            scene,
            visual_type="title_card",
            visual_data={"topic": _short_label(topic, 180), "subtitle": subtitle},
            title=title,
        )

    # The planner sometimes puts a renderer name inside visual_data while the
    # actual visual_type remains its default "concept". Promote only known
    # built-in names and discard the metadata key before rendering.
    visual_type = scene.visual_type
    if visual_type in {"concept", "flow"} and embedded_hint:
        visual_type = embedded_hint

    # The first teaching scene gets the most specific deterministic strategy
    # available from a typed payload, a structured legacy field, or a simple
    # topic expression. Later scenes can remain applications/recaps chosen by
    # the planner instead of being forced into one repeated template.
    specialized_first_scene = scene_index == 1
    if specialized_first_scene and visual_type in {
        "concept",
        "concept_diagram",
        "flow",
        "process_flow",
    }:
        engineering = _engineering_strategy(topic)
        if engineering is not None:
            strategy, payload = engineering
            if strategy == "cycle" and isinstance(payload, CycleData):
                return _with_visual(
                    scene,
                    visual_type="cycle",
                    visual_data={},
                    cycle_data=payload,
                )
            if strategy == "process_flow" and isinstance(payload, dict):
                return _with_visual(
                    scene,
                    visual_type="process_flow",
                    visual_data=payload,
                )

    has_simple_arithmetic = any(
        re.search(
            r"(?<![\w.])-?\d{1,2}\s*[+-]\s*-?\d{1,2}(?:\s*=\s*-?\d{1,2})?(?![\w.])",
            candidate,
        )
        for candidate in (topic, scene.title)
    )
    if visual_type == "number_line" or (
        specialized_first_scene
        and (
            has_simple_arithmetic
            or re.search(r"\b(number line|integer arithmetic|negative numbers?)\b", topic, re.I)
        )
    ):
        number_line = _number_line_data(topic, scene, data)
        if number_line is not None:
            return _with_visual(
                scene,
                visual_type="number_line",
                visual_data={},
                number_line_data=number_line,
            )

    if visual_type == "equation_steps" or (specialized_first_scene and EQUATION_TOPIC.search(topic)):
        equation_steps = _equation_steps_data(topic, scene, data)
        if equation_steps is not None:
            return _with_visual(
                scene,
                visual_type="equation_steps",
                visual_data={},
                equation_steps_data=equation_steps,
            )

    if visual_type == "cycle" or (specialized_first_scene and CYCLE_TOPIC.search(topic)):
        cycle = _cycle_data(topic, scene, data)
        if cycle is not None:
            return _with_visual(
                scene,
                visual_type="cycle",
                visual_data={},
                cycle_data=cycle,
            )

    fraction = _fraction_data(topic, scene, data)
    if fraction is not None:
        return _with_visual(
            scene,
            visual_type="fraction_model",
            visual_data={},
            fraction_data=fraction,
        )

    cause_effect = scene.cause_effect_data or _cause_effect_data(data)
    if cause_effect is None and PHOTOSYNTHESIS_TOPIC.search(topic) and scene_index == 1:
        # This is the same curated, deterministic model already used by Blu's
        # offline sample lesson, applied when the planner omits typed fields.
        cause_effect = CauseEffectData(
            inputs=["sunlight", "water", "carbon dioxide"],
            mechanism="chloroplasts in a leaf",
            outputs=["glucose", "oxygen"],
        )
    if cause_effect is not None:
        return _with_visual(
            scene,
            visual_type="cause_effect",
            visual_data={},
            cause_effect_data=cause_effect,
        )

    if is_programming_topic(topic):
        if scene.execution_data is not None:
            return _with_visual(
                scene,
                visual_type="code_execution",
                visual_data=data,
                execution_data=scene.execution_data,
            )
    elif visual_type in {"code", "code_execution"}:
        visual_type = "concept_diagram"

    if visual_type in {"flow", "process_flow"}:
        flow_data = _ordered_flow_data(data, scene)
        if flow_data is not None:
            return _with_visual(scene, visual_type="process_flow", visual_data=flow_data)
        visual_type = "concept_diagram"

    if visual_type in {"fraction_model", "cause_effect", "number_line", "equation_steps", "cycle"}:
        # Malformed specialized data is never sent to a renderer as if it were
        # valid. Use an informative built-in concept diagram instead.
        visual_type = "concept_diagram"

    if visual_type == "title_card":
        # Preserve explicitly requested title cards after the opener. The
        # planner prompt asks for only one; the opener itself is normalized
        # above even when a small model labels it as a generic concept.
        return _with_visual(
            scene,
            visual_type="title_card",
            visual_data={
                "topic": _short_label(data.get("topic") or scene.title),
                "subtitle": _short_label(data.get("subtitle") or scene.caption),
            },
        )

    # Recover useful ordered stages from legacy descriptions such as
    # "Sunlight -> raindrops -> rainbow" before falling back to a diagram.
    # This keeps the actual labels while routing them through the same safe
    # process-flow component used by preview and MP4 rendering.
    if visual_type in {"concept", "concept_diagram"}:
        flow_data = _ordered_flow_data(data, scene)
        if flow_data is not None:
            return _with_visual(scene, visual_type="process_flow", visual_data=flow_data)

    normalized_data = _concept_diagram_data(data, topic, scene)
    return _with_visual(
        scene,
        visual_type="concept_diagram",
        visual_data=normalized_data,
    )


def renderer_key(scene: Scene) -> str:
    """Resolve both current names and legacy names to a typed renderer key."""
    if scene.visual_type == "title_card":
        return "title_card"
    if scene.visual_type in {"concept", "concept_diagram"}:
        return "concept_diagram"
    if scene.visual_type in {"flow", "process_flow"}:
        return "process_flow"
    if scene.visual_type == "code_execution" and scene.execution_data is not None:
        return "code_execution"
    if scene.visual_type == "fraction_model" and scene.fraction_data is not None:
        return "fraction_model"
    if scene.visual_type == "cause_effect" and scene.cause_effect_data is not None:
        return "cause_effect"
    if scene.visual_type == "number_line" and scene.number_line_data is not None:
        return "number_line"
    if scene.visual_type == "equation_steps" and scene.equation_steps_data is not None:
        return "equation_steps"
    if scene.visual_type == "cycle" and scene.cycle_data is not None:
        return "cycle"
    if scene.visual_type in {"fraction_model", "cause_effect", "number_line", "equation_steps", "cycle"}:
        return "concept_diagram"
    return "legacy_code"


def build_code_execution_timeline(
    data: CodeExecutionData,
) -> list[dict[str, Any]]:
    """Build normalized keyframes shared by the video renderer and browser.

    The data is declarative: this function creates display states only. It never
    parses or evaluates model-generated Python code.
    """
    count = len(data.values)
    ready_end = 0.1
    complete_start = 0.9
    step_width = (complete_start - ready_end) / count
    keyframes: list[dict[str, Any]] = [
        {
            "start_progress": 0.0,
            "end_progress": ready_end,
            "phase": "ready",
            "active_line": 1,
            "iteration": 0,
            "value": None,
            "output": [],
            "status": "Ready to begin",
        }
    ]
    for index, value in enumerate(data.values):
        start = ready_end + index * step_width
        middle = start + step_width * 0.38
        end = start + step_width
        previous_output = data.values[:index]
        keyframes.extend(
            [
                {
                    "start_progress": start,
                    "end_progress": middle,
                    "phase": "next_value",
                    "active_line": 1,
                    "iteration": index + 1,
                    "value": value,
                    "output": previous_output,
                    "status": f"Read item {index + 1} of {count}",
                },
                {
                    "start_progress": middle,
                    "end_progress": end,
                    "phase": "run_body",
                    "active_line": 2,
                    "iteration": index + 1,
                    "value": value,
                    "output": data.values[: index + 1],
                    "status": f"Print {value}",
                },
            ]
        )
    keyframes.append(
        {
            "start_progress": complete_start,
            "end_progress": 1.0,
            "phase": "complete",
            "active_line": 1,
            "iteration": count,
            "value": None,
            "output": data.values,
            "status": "No values remain · loop stops",
        }
    )
    return keyframes


def visual_state_at_progress(
    keyframes: list[dict[str, Any]], progress: float
) -> dict[str, Any] | None:
    if not keyframes:
        return None
    bounded = max(0.0, min(1.0, float(progress)))
    for frame in keyframes:
        if bounded < frame["end_progress"]:
            return frame
    return keyframes[-1]
