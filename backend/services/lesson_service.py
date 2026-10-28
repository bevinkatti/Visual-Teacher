from uuid import uuid4
import re

from backend.schemas import (
    CauseEffectData,
    CodeExecutionData,
    FallbackReason,
    FractionModelData,
    Lesson,
    LessonRequest,
    Scene,
)
from backend.services.duration_budget import speaking_rate, spoken_length


PYTHON_LOOP_TOPICS = {
    "how python code works",
    "python",
    "how does a python loop work?",
    "how does a python loop work",
    "python loops",
    "how python for-loops work",
    "how python for loops work",
    "how do python for loops work",
}
FRACTION_TOPIC = re.compile(r"\b(fractions?|parts of a whole|one half|one third|one quarter)\b", re.I)
PHOTOSYNTHESIS_TOPIC = re.compile(r"photosynth", re.I)

DEFAULT_PAUSE_SECONDS = 0.35


def _scene_count_for(duration_seconds: int) -> int:
    """Shorter lessons stay tight; longer lessons earn a recap scene."""
    return 3 if duration_seconds <= 45 else 4


def _fit_pool(sentences: list[str], char_budget: int) -> str:
    """Join whole leading sentences until the scene's spoken-length budget is filled."""
    kept: list[str] = []
    total = 0
    for index, sentence in enumerate(sentences):
        addition = spoken_length(sentence) + (1 if kept else 0)
        if index > 0 and total + addition > char_budget:
            break
        kept.append(sentence)
        total += addition
    return " ".join(kept)


def _fill_pools_round_robin(
    pools: list[list[str]], total_units: int
) -> tuple[list[str], list[list[str]]]:
    """Fill scene pools one sentence each, round-robin, until the budget is spent.

    Round-robin keeps scene pacing even and loses at most one sentence to
    granularity (a proportional splitter loses one sentence per scene). The
    render-time duration guard still trims any overshoot. Returns the joined
    fills and each pool's unused tail (for measured growth at render time).
    """
    fills: list[list[str]] = [[] for _ in pools]
    totals = [0] * len(pools)
    positions = [0] * len(pools)
    remaining = total_units
    # Keep scene pacing balanced: no scene may exceed this multiple of an
    # equal share, so a long early scene cannot starve the closing scene.
    cap = max(40, int(total_units / len(pools) * 1.35))
    progress_made = True
    while remaining > 0 and progress_made:
        progress_made = False
        for index, pool in enumerate(pools):
            if positions[index] >= len(pool):
                continue
            sentence = pool[positions[index]]
            units = spoken_length(sentence) + (1 if totals[index] else 0)
            if totals[index] + units > cap:
                continue
            if units <= remaining:
                fills[index].append(sentence)
                totals[index] += units
                remaining -= units
                positions[index] += 1
                progress_made = True
    narrations = [
        " ".join(fill) if fill else (pool[0] if pool else "")
        for fill, pool in zip(fills, pools, strict=True)
    ]
    remainders = [
        pool[position:] if fill else [] for pool, position, fill in zip(pools, positions, fills, strict=True)
    ]
    return narrations, remainders


def _build_scenes_from_templates(
    language: str,
    templates: list[dict],
    duration_seconds: int,
) -> tuple[list[Scene], dict[int, list[str]]]:
    """Build scenes from authored sentence pools sized for the target duration.

    Pool text is deterministic fallback content: whole sentences only, and the
    duration_budget guard trims anything that still overshoots after this.
    Also returns each scene's unused pool tail so the exporter can GROW
    under-running narrations from measured audio (sample lessons only).
    """
    templates = templates[: _scene_count_for(duration_seconds)]
    engine = "parler" if language == "kn" else "kokoro"
    rate = speaking_rate(engine, language)
    pauses = DEFAULT_PAUSE_SECONDS * len(templates)
    # Fill at 80% of the calibrated rate on purpose: real per-sentence speaking
    # rates swing far more than any constant can track, so scenes keep a pool
    # RESERVE and the exporter's measured growth pass tops them up toward the
    # target using actual audio. The shrink pass still trims any overshoot.
    speech_seconds = max(3.0, (duration_seconds - pauses) * 0.8)
    fills, remainders = _fill_pools_round_robin(
        [template["narration_pool"] for template in templates],
        int(speech_seconds * rate),
    )
    scenes = []
    for template, narration in zip(templates, fills, strict=True):
        scenes.append(
            Scene(
                title=template["title"],
                narration=narration,
                caption=template["caption"],
                visual_type=template["visual_type"],
                visual_data=template["visual_data"],
                execution_data=template.get("execution_data"),
                fraction_data=template.get("fraction_data"),
                cause_effect_data=template.get("cause_effect_data"),
                pause_seconds=DEFAULT_PAUSE_SECONDS,
            )
        )
    grow_pool = {
        index: tail for index, tail in enumerate(remainders) if tail
    }
    return scenes, grow_pool



def _python_loop_templates_en(topic: str) -> list[dict]:
    return [
        {
            "title": "One loop, one turn per item",
            "caption": "A for loop gives each list item one turn.",
            "visual_type": "title_card",
            "visual_data": {
                "topic": topic,
                "subtitle": "One for loop visits each item in order.",
            },
            "narration_pool": [
                "A for loop repeats one instruction for every value in a list.",
                "Instead of copying the same line again and again, you write it once.",
                "We will watch three fruits travel through the loop, one turn at a time.",
                "By the end, you will predict the output before Python prints it.",
                "Each value in the list gets exactly one turn.",
                "Once you see the pattern, longer loops feel exactly the same.",
            ],
        },
        {
            "title": "Watch each pass update the output",
            "caption": "fruit changes on each pass; output grows one line at a time.",
            "visual_type": "code_execution",
            "visual_data": {"purpose": "One iteration per list item."},
            "execution_data": CodeExecutionData(
                variable_name="fruit",
                iterable_name="fruits",
                values=["apple", "pear", "plum"],
            ),
            "narration_pool": [
                "Python starts at the loop line and takes the first value, apple.",
                "It puts apple into the variable fruit and runs the print instruction.",
                "The output shows apple on its own line.",
                "On the next pass, fruit becomes pear, and pear is printed the same way.",
                "Then fruit becomes plum, and the output gains plum.",
                "Notice the instruction never changes; only the value inside fruit does.",
                "Watch the output panel grow by one line per pass.",
                "After the last value, Python stops without printing anything more.",
            ],
        },
        {
            "title": "No next value means the loop stops",
            "caption": "Three items produce three lines; no next item means stop.",
            "visual_type": "concept_diagram",
            "visual_data": {
                "left": "3 passes",
                "right": "3 output lines",
                "relationship": "no next item → stop",
            },
            "narration_pool": [
                "Each pass takes the next value and runs it once.",
                "When the list has no next value, Python leaves the loop.",
                "Three list values produced exactly three output lines.",
                "That is why a for loop never runs forever.",
                "The loop ends on its own; you never switch it off by hand.",
                "Predicting the final line is the best test of understanding.",
            ],
        },
        {
            "title": "Read any loop in three steps",
            "caption": "Find the list, the variable, and the instruction.",
            "visual_type": "process_flow",
            "visual_data": {"input": "Find", "process": "Trace", "output": "Predict"},
            "narration_pool": [
                "To read any loop, find the list, the variable, and the instruction.",
                "Trace one pass at a time, and write down the output as it grows.",
                "If you can predict the last line, you understand the loop.",
                "Practice on any list you like; the reading steps never change.",
            ],
        },
    ]


def _fraction_templates_en(topic: str) -> list[dict]:
    return [
        {
            "title": "Fractions divide one whole equally",
            "caption": "The denominator counts equal pieces; the numerator counts selected pieces.",
            "visual_type": "title_card",
            "visual_data": {
                "topic": topic,
                "subtitle": "Divide one whole, then count the equal pieces you select.",
            },
            "narration_pool": [
                "A fraction describes part of one whole that has been split into equal pieces.",
                "We will use three quarters to make the two fraction numbers visible.",
                "The denominator answers how many equal pieces make the whole.",
                "The numerator answers how many of those pieces we select.",
            ],
        },
        {
            "title": "Shade three of four equal parts",
            "caption": "Four equal parts make the whole; three selected parts are 3/4.",
            "visual_type": "fraction_model",
            "visual_data": {},
            "fraction_data": FractionModelData(numerator=3, denominator=4),
            "narration_pool": [
                "First the bar is split into four equal-sized cells, so the whole stays the same size.",
                "The denominator is four because all four cells make one whole.",
                "Now three cells fill in; the numerator is three because we selected three parts.",
                "So the shaded amount is three fourths, written as three over four.",
            ],
        },
        {
            "title": "Read the numerator over the denominator",
            "caption": "Numerator: selected pieces. Denominator: all equal pieces.",
            "visual_type": "process_flow",
            "visual_data": {
                "input": "One whole",
                "process": "Split into 4; select 3",
                "output": "3/4 of the whole",
            },
            "narration_pool": [
                "The same whole remains underneath the fraction.",
                "Count selected equal pieces for the top number, the numerator.",
                "Count all equal pieces for the bottom number, the denominator.",
                "Three selected out of four equal pieces is three fourths.",
            ],
        },
        {
            "title": "Check both numbers against the bar",
            "caption": "A fraction names selected equal pieces out of the whole.",
            "visual_type": "concept_diagram",
            "visual_data": {
                "left": "3 selected parts",
                "right": "4 equal parts in all",
                "relationship": "fraction = selected / total",
            },
            "narration_pool": [
                "If the shaded parts are not equal, the bar is not showing fourths.",
                "The top number must match the shaded cells you can count.",
                "The bottom number must match every equal cell in the whole.",
                "Use those two counts to explain the fraction in your own words.",
            ],
        },
    ]


def _photosynthesis_templates_en(topic: str) -> list[dict]:
    mechanism = CauseEffectData(
        inputs=["sunlight", "water", "carbon dioxide"],
        mechanism="chloroplasts in a leaf",
        outputs=["glucose", "oxygen"],
    )
    return [
        {
            "title": "Plants use light to make sugars",
            "caption": "Follow the inputs into the leaf and the products back out.",
            "visual_type": "title_card",
            "visual_data": {
                "topic": topic,
                "subtitle": "Trace sunlight, water, and carbon dioxide through a leaf.",
            },
            "narration_pool": [
                "Photosynthesis changes light energy into chemical energy stored in sugar.",
                "A green plant takes in water and carbon dioxide as materials for the process.",
                "We will follow those inputs into a leaf and watch what comes out.",
                "The key change happens inside chloroplasts in plant cells.",
            ],
        },
        {
            "title": "Inputs enter; products leave",
            "caption": "Light, water, and carbon dioxide lead to glucose and oxygen.",
            "visual_type": "cause_effect",
            "visual_data": {},
            "cause_effect_data": mechanism,
            "narration_pool": [
                "Sunlight supplies energy, while water and carbon dioxide supply matter.",
                "Inside leaf cells, chloroplasts use that light energy to build glucose.",
                "The plant stores chemical energy in the glucose for growth and cell work.",
                "Oxygen is produced as the process releases its other product.",
            ],
        },
        {
            "title": "Track the matter through the leaf",
            "caption": "Carbon dioxide and water become glucose; oxygen is released.",
            "visual_type": "process_flow",
            "visual_data": {
                "input": "Water + carbon dioxide",
                "process": "Light energy in chloroplasts",
                "output": "Glucose + oxygen",
            },
            "narration_pool": [
                "The atoms in water and carbon dioxide are rearranged into new molecules.",
                "Light provides energy for that change; it is not matter in the sugar.",
                "Glucose stores some of the captured energy in chemical bonds.",
                "The plant releases oxygen, while the sugar supports growth and repair.",
            ],
        },
        {
            "title": "Remember the transformation",
            "caption": "Light energy helps chloroplasts turn inputs into useful products.",
            "visual_type": "concept_diagram",
            "visual_data": {
                "left": "Water + carbon dioxide",
                "right": "Glucose + oxygen",
                "relationship": "light energy in chloroplasts",
            },
            "narration_pool": [
                "Light is the energy source, and water and carbon dioxide are the matter inputs.",
                "Chloroplasts are the cell structures where photosynthesis takes place.",
                "Glucose stores energy for the plant, and oxygen leaves as a product.",
                "Explain the change by naming its inputs, mechanism, and outputs.",
            ],
        },
    ]



def _python_loop_templates_hi(topic: str) -> list[dict]:
    return [
        {
            "title": "हर सूची वस्तु की एक बारी",
            "caption": "फ़ॉर लूप सूची की हर वस्तु को एक बारी देता है।",
            "visual_type": "title_card",
            "visual_data": {
                "topic": topic,
                "subtitle": "एक फ़ॉर लूप, सूची की हर वस्तु के लिए एक बार चलता है।",
            },
            "narration_pool": [
                "फ़ॉर लूप सूची की हर वस्तु के लिए एक निर्देश दोहराता है।",
                "सूची की हर वस्तु को ठीक एक ही बारी मिलती है।",
                "हम तीन फलों को लूप से होते हुए एक-एक करके देखेंगे।",
                "अंत तक आप आउटपुट पहले से बता पाएँगे।",
                "एक ही निर्देश बार-बार लिखने की जगह, हम उसे पूरी सूची के लिए एक बार लिखते हैं।",
                "एक बार पैटर्न दिख जाए, तो लंबे लूप भी उतने ही आसान लगते हैं।",
                "हर बारी में निर्देश वही रहता है।",
                "बस मान बदलता जाता है।",
            ],
        },
        {
            "title": "हर चक्र में बदलता मान",
            "caption": "हर चक्र में fruit बदलता है और आउटपुट में एक पंक्ति जुड़ती है।",
            "visual_type": "code_execution",
            "visual_data": {"purpose": "हर सूची वस्तु के लिए एक चक्र।"},
            "execution_data": CodeExecutionData(
                variable_name="fruit",
                iterable_name="fruits",
                values=["apple", "pear", "plum"],
            ),
            "narration_pool": [
                "पायथन लूप की पंक्ति से शुरू होकर पहली वस्तु apple को fruit में रखता है।",
                "फिर print निर्देश चलता है और आउटपुट में apple जुड़ जाता है।",
                "अगली बार fruit का मान pear बन जाता है, और pear भी इसी तरह छपता है।",
                "फिर fruit plum बनता है, और आउटपुट में plum जुड़ जाता है।",
                "ध्यान दें, निर्देश कभी नहीं बदलता; केवल fruit के अंदर का मान बदलता है।",
                "हर चक्र के साथ आउटपुट में एक नई पंक्ति जुड़ती दिखेगी।",
                "अंतिम वस्तु के बाद पायथन बिना कुछ और छपाए रुक जाता है।",
                "आउटपुट धीरे-धीरे बढ़ता जाता है।",
                "अगली वस्तु के लिए वही काम दोहराया जाता है।",
            ],
        },
        {
            "title": "अगली वस्तु न हो तो लूप रुकता है",
            "caption": "तीन वस्तुएँ, तीन पंक्तियाँ; अगली वस्तु नहीं तो लूप बंद।",
            "visual_type": "concept_diagram",
            "visual_data": {
                "left": "तीन चक्र",
                "right": "तीन पंक्तियाँ",
                "relationship": "अगली वस्तु नहीं → रुकें",
            },
            "narration_pool": [
                "हर चक्र अगली वस्तु लेता है और वही निर्देश एक बार चलाता है।",
                "इसीलिए फ़ॉर लूप कभी हमेशा तक नहीं चलता।",
                "इस तरह सूची की तीन वस्तुओं से ठीक तीन आउटपुट पंक्तियाँ बनीं।",
                "जब सूची में अगली वस्तु नहीं बचती, पायथन लूप से बाहर आ जाता है।",
                "लूप अपने आप समाप्त हो जाता है; आपको उसे बंद नहीं करना पड़ता।",
                "अंतिम पंक्ति का अनुमान लगाना ही समझ की सबसे अच्छी परीक्षा है।",
                "इतने में लूप पूरा हो जाता है।",
                "नतीजा तीन साफ़ पंक्तियाँ हैं।",
            ],
        },
        {
            "title": "तीन कदम में कोई भी लूप पढ़ें",
            "caption": "सूची, वेरिएबल और निर्देश पहचानें।",
            "visual_type": "process_flow",
            "visual_data": {"input": "पहचानें", "process": "चलें", "output": "बताएँ"},
            "narration_pool": [
                "किसी भी लूप को पढ़ने के लिए सूची, वेरिएबल और निर्देश पहचानें।",
                "एक समय में एक चक्र अनुसरण करें और बढ़ते आउटपुट को लिखते जाएँ।",
                "अगर आप अंतिम पंक्ति पहले ही बता सकते हैं, तो आपने लूप समझ लिया।",
                "किसी भी सूची पर अभ्यास करें; पढ़ने के चरण कभी नहीं बदलते।",
            ],
        },
    ]


def _python_loop_templates_kn(topic: str) -> list[dict]:
    return [
        {
            "title": "ಪ್ರತಿ ವಸ್ತುವಿಗೂ ಒಂದು ಸಲ",
            "caption": "ಫಾರ್ ಲೂಪ್ ಪಟ್ಟಿಯ ಪ್ರತಿ ವಸ್ತುವಿಗೂ ಒಂದು ಸಲ ಕೊಡುತ್ತದೆ.",
            "visual_type": "title_card",
            "visual_data": {
                "topic": topic,
                "subtitle": "ಒಂದು ಫಾರ್ ಲೂಪ್ ಪಟ್ಟಿಯ ಪ್ರತಿ ವಸ್ತುವಿಗೂ ಒಮ್ಮೆ ಚಲಿಸುತ್ತದೆ.",
            },
            "narration_pool": [
                "ಫಾರ್ ಲೂಪ್ ಪಟ್ಟಿಯಲ್ಲಿನ ಪ್ರತಿ ಮೌಲ್ಯಕ್ಕೂ ಒಂದು ಸೂಚನೆಯನ್ನು ಪುನರಾವರ್ತಿಸುತ್ತದೆ.",
                "ಪ್ರತಿ ಮೌಲ್ಯಕ್ಕೂ ಒಂದೇ ಸಲ ಸಿಗುತ್ತದೆ.",
                "ಮೂರು ಹಣ್ಣುಗಳು ಲೂಪ್ ಒಳಗೆ ಒಂದೊಂದಾಗಿ ಹೇಗೆ ಸಾಗುತ್ತವೆ ಎಂದು ನೋಡೋಣ.",
                "ಕೊನೆಗೆ ಔಟ್‌ಪುಟ್ ಅನ್ನು ಮೊದಲೇ ಹೇಳಲು ನಿಮಗೆ ಸಾಧ್ಯವಾಗುತ್ತದೆ.",
                "ಒಂದೇ ಸೂಚನೆಯನ್ನು ಬಾರಿ ಬಾರಿ ಬರೆಯುವ ಬದಲು, ಅದನ್ನು ಒಮ್ಮೆ ಮಾತ್ರ ಬರೆಯುತ್ತೇವೆ.",
                "ಪಟ್ಟಿಯ ಪ್ರತಿ ಮೌಲ್ಯಕ್ಕೂ ನಿಖರವಾಗಿ ಒಂದೇ ಒಂದು ಸಲ ಸಿಗುತ್ತದೆ.",
                "ಮಾದರಿ ಒಮ್ಮೆ ಕಂಡುಬಂತೆ, ಉದ್ದದ ಲೂಪ್‌ಗಳೂ ಅಷ್ಟೇ ಸುಲಭವಾಗಿ ಕಾಣುತ್ತವೆ.",
            ],
        },
        {
            "title": "ಪ್ರತಿ ಸುತ್ತಿನಲ್ಲೂ ಔಟ್‌ಪುಟ್ ಬದಲಾಗುತ್ತದೆ",
            "caption": "ಪ್ರತಿ ಸುತ್ತಿನಲ್ಲೂ fruit ಬದಲಾಗುತ್ತದೆ; ಔಟ್‌ಪುಟ್ ಬೆಳೆಯುತ್ತದೆ.",
            "visual_type": "code_execution",
            "visual_data": {"purpose": "ಪ್ರತಿ ಪಟ್ಟಿ ವಸ್ತುವಿಗೂ ಒಂದು ಸುತ್ತು."},
            "execution_data": CodeExecutionData(
                variable_name="fruit",
                iterable_name="fruits",
                values=["apple", "pear", "plum"],
            ),
            "narration_pool": [
                "ಪೈಥಾನ್ ಲೂಪ್ ಸಾಲಿನಿಂದ ಶುರುವಾಗಿ ಮೊದಲ ವಸ್ತುವಾದ apple ಅನ್ನು ತೆಗೆದುಕೊಳ್ಳುತ್ತದೆ.",
                "ಔಟ್‌ಪುಟ್‌ನಲ್ಲಿ apple ಒಂದು ಸಾಲಾಗಿ ಸೇರುತ್ತದೆ.",
                "ಅದು apple ಅನ್ನು fruit ಎಂಬ ಚರದಲ್ಲಿಟ್ಟು print ಸೂಚನೆಯನ್ನು ಚಲಾಯಿಸುತ್ತದೆ.",
                "ಮುಂದಿನ ಸುತ್ತಿನಲ್ಲಿ fruit ನ ಮೌಲ್ಯ pear ಆಗುತ್ತದೆ, pear ಕೂಡ ಹಾಗೆಯೇ ಮುದ್ರಿತವಾಗುತ್ತದೆ.",
                "ನಂತರ fruit plum ಆಗುತ್ತದೆ, ಔಟ್‌ಪುಟ್‌ಗೆ plum ಸೇರುತ್ತದೆ.",
                "ಸೂಚನೆ ಎಂದಿಗೂ ಬದಲಾಗುವುದಿಲ್ಲ; fruit ಒಳಗಿನ ಮೌಲ್ಯ ಮಾತ್ರ ಬದಲಾಗುತ್ತದೆ.",
                "ಪ್ರತಿ ಸುತ್ತಿನೊಂದಿಗೆ ಔಟ್‌ಪುಟ್‌ಗೆ ಒಂದು ಹೊಸ ಸಾಲು ಸೇರುತ್ತದೆ.",
                "ಕೊನೆಯ ಮೌಲ್ಯದ ನಂತರ ಪೈಥಾನ್ ಇನ್ನು ಏನನ್ನೂ ಮುದ್ರಿಸದೆ ನಿಲ್ಲುತ್ತದೆ.",
            ],
        },
        {
            "title": "ಮುಂದಿನ ಮೌಲ್ಯ ಇಲ್ಲದಿದ್ದರೆ ಲೂಪ್ ನಿಲ್ಲುತ್ತದೆ",
            "caption": "ಮೂರು ವಸ್ತುಗಳು, ಮೂರು ಸಾಲುಗಳು; ಮುಂದಿನ ವಸ್ತು ಇಲ್ಲದಿದ್ದರೆ ನಿಲ್ಲುತ್ತದೆ.",
            "visual_type": "concept_diagram",
            "visual_data": {
                "left": "3 ಸುತ್ತುಗಳು",
                "right": "3 ಔಟ್‌ಪುಟ್ ಸಾಲುಗಳು",
                "relationship": "ಮುಂದಿನ ವಸ್ತು ಇಲ್ಲ → ನಿಲ್ಲಿಸಿ",
            },
            "narration_pool": [
                "ಪ್ರತಿ ಸುತ್ತು ಮುಂದಿನ ಮೌಲ್ಯವನ್ನು ತೆಗೆದುಕೊಂಡು ಅದೇ ಸೂಚನೆಯನ್ನು ಒಮ್ಮೆ ಚಲಾಯಿಸುತ್ತದೆ.",
                "ಇದೇ ಕಾರಣಕ್ಕೆ ಫಾರ್ ಲೂಪ್ ಎಂದಿಗೂ ಶಾಶ್ವತವಾಗಿ ಓಡುವುದಿಲ್ಲ.",
                "ಪಟ್ಟಿಯ ಮೂರು ಮೌಲ್ಯಗಳು ನಿಖರವಾಗಿ ಮೂರು ಔಟ್‌ಪುಟ್ ಸಾಲುಗಳನ್ನು ಉಂಟುಮಾಡಿದವು.",
                "ಪಟ್ಟಿಯಲ್ಲಿ ಮುಂದಿನ ವಸ್ತು ಇಲ್ಲದಿದ್ದಾಗ, ಪೈಥಾನ್ ಲೂಪ್‌ನಿಂದ ಹೊರಬರುತ್ತದೆ.",
                "ಲೂಪ್ ತಾನೇ ಮುಕ್ತಾಯಗೊಳ್ಳುತ್ತದೆ; ನೀವು ಅದನ್ನು ಸ್ವಯಂ ಮುಚ್ಚಬೇಕಿಲ್ಲ.",
                "ಕೊನೆಯ ಸಾಲನ್ನು ಊಹಿಸುವುದೇ ಅರ್ಥಮಾಡಿಕೊಳ್ಳುವಿಕೆಯ ಅತ್ಯುತ್ತಮ ಪರೀಕ್ಷೆ.",
            ],
        },
        {
            "title": "ಮೂರು ಹಂತಗಳಲ್ಲಿ ಯಾವುದೇ ಲೂಪ್ ಓದಿ",
            "caption": "ಪಟ್ಟಿ, ಚರ ಮತ್ತು ಸೂಚನೆಯನ್ನು ಗುರುತಿಸಿ.",
            "visual_type": "process_flow",
            "visual_data": {"input": "ಗುರುತಿಸಿ", "process": "ಅನುಸರಿಸಿ", "output": "ಹೇಳಿ"},
            "narration_pool": [
                "ಯಾವುದೇ ಲೂಪ್ ಅನ್ನು ಓದಲು ಪಟ್ಟಿ, ಚರ ಮತ್ತು ಸೂಚನೆಯನ್ನು ಗುರುತಿಸಿ.",
                "ಒಂದೊಂದು ಸುತ್ತನ್ನು ಹಂತ ಹಂತವಾಗಿ ಅನುಸರಿಸಿ, ಬೆಳೆಯುತ್ತಿರುವ ಔಟ್‌ಪುಟ್ ಬರೆಯಿರಿ.",
                "ಕೊನೆಯ ಸಾಲನ್ನು ಮೊದಲೇ ಊಹಿಸಬಲ್ಲಿದ್ದರೆ, ನೀವು ಲೂಪ್ ಅನ್ನು ಅರ್ಥಮಾಡಿಕೊಂಡಿದ್ದೀರಿ.",
                "ಇಷ್ಟದ ಯಾವುದೇ ಪಟ್ಟಿಯ ಮೇಲೆ ಅಭ್ಯಾಸ ಮಾಡಿ; ಓದುವ ಹಂತಗಳು ಬದಲಾಗುವುದಿಲ್ಲ.",
            ],
        },
    ]


def _generic_templates_en(topic: str) -> list[dict]:
    return [
        {
            "title": "Start with the idea",
            "caption": f"The central idea: {topic}",
            "visual_type": "title_card",
            "visual_data": {
                "topic": topic,
                "subtitle": "Start with the core idea, then build understanding.",
            },
            "narration_pool": [
                f"Let's explore {topic} in small, friendly steps.",
                f"First we find the main idea behind {topic}.",
                "Then we connect that idea to one concrete example.",
                f"By the end, you can explain {topic} in your own words.",
            ],
        },
        {
            "title": "Break it into steps",
            "caption": "Break a complex idea into smaller parts.",
            "visual_type": "process_flow",
            "visual_data": {"input": "Observe", "process": "Understand", "output": "Explain"},
            "narration_pool": [
                f"We start by observing {topic} in action.",
                "Next we slow down and understand each part of it.",
                "One part at a time keeps the full idea easy to hold.",
                "Finally we explain it back, which locks the learning in place.",
            ],
        },
        {
            "title": "Check your understanding",
            "caption": "Explain it in your own words.",
            "visual_type": "concept_diagram",
            "visual_data": {"left": "Example", "right": "Understanding", "relationship": "explain → mastered"},
            "narration_pool": [
                f"The key idea of {topic} answers one clear question.",
                "A good example makes the idea easy to picture.",
                "When you can teach it simply, you truly understand it.",
                "Try explaining it to a friend and notice which part feels hard.",
            ],
        },
        {
            "title": "Walk it once more",
            "caption": "Revisit the main question and the steps.",
            "visual_type": "process_flow",
            "visual_data": {"input": "Question", "process": "Steps", "output": "Answer"},
            "narration_pool": [
                f"To revisit {topic}, start from its main question.",
                "Walk the steps again and watch where each one leads.",
                "If any step feels shaky, that is exactly where to practice.",
            ],
        },
    ]


def _generic_templates_hi(topic: str) -> list[dict]:
    return [
        {
            "title": "मुख्य विचार से शुरुआत",
            "caption": f"मुख्य विचार: {topic}",
            "visual_type": "title_card",
            "visual_data": {"topic": topic, "subtitle": "मुख्य विचार से चरण-दर-चरण सीखें।"},
            "narration_pool": [
                f"आइए “{topic}” को छोटे चरणों में समझें।",
                f"पहले हम “{topic}” के पीछे का मुख्य विचार पहचानते हैं।",
                "फिर उस विचार को एक ठोस उदाहरण से जोड़ते हैं।",
                "अंत तक आप इसे अपने शब्दों में समझा सकते हैं।",
            ],
        },
        {
            "title": "इसे छोटे चरणों में बाँटें",
            "caption": "बड़े विचार को छोटे चरणों में समझें।",
            "visual_type": "process_flow",
            "visual_data": {"input": "देखें", "process": "समझें", "output": "समझाएँ"},
            "narration_pool": [
                f"हम “{topic}” को काम करते हुए देखकर शुरू करते हैं।",
                "फिर रुककर उसके हिस्से को समझते हैं।",
                "एक समय में एक भाग देखने से पूरा विचार आसान रहता है।",
                "अंत में उसे अपने शब्दों में समझाने से सीख पक्की होती है।",
            ],
        },
        {
            "title": "अपनी समझ जाँचें",
            "caption": "अपने शब्दों में उदाहरण सहित समझाएँ।",
            "visual_type": "concept_diagram",
            "visual_data": {"left": "उदाहरण", "right": "समझ", "relationship": "समझाएँ → पक्की"},
            "narration_pool": [
                f"“{topic}” का मुख्य विचार एक स्पष्ट प्रश्न का उत्तर देता है।",
                "अच्छा उदाहरण विचार को दिमाग में चित्रित कर देता है।",
                "जब आप उसे सरल शब्दों में पढ़ा सकते हैं, तो समझ पूरी होती है।",
                "किसी मित्र को समझाकर देखें कि कौन-सा भाग कठिन लगता है।",
            ],
        },
        {
            "title": "एक बार फिर चलें",
            "caption": "मुख्य प्रश्न और चरणों को दोहराएँ।",
            "visual_type": "process_flow",
            "visual_data": {"input": "प्रश्न", "process": "चरण", "output": "उत्तर"},
            "narration_pool": [
                f"“{topic}” को दोहराने के लिए उसके मुख्य प्रश्न से शुरू करें।",
                "चरणों को फिर से चलें और देखें कि हर चरण कहाँ ले जाता है।",
                "जो चरण कमज़ोर लगे, अभ्यास ठीक वहीं करना चाहिए।",
            ],
        },
    ]


def build_sample_lesson_with_pool(
    request: LessonRequest,
    *,
    fallback_reason: FallbackReason | None = None,
) -> tuple[Lesson, dict[int, list[str]]]:
    """Fallback lesson plus each scene's unused narration tail.

    The exporter grows under-running scenes from these tails using measured
    audio, so a 30-second fallback lesson lands near 30 seconds even when the
    estimate is off. Model-planned lessons have no pool and never grow.
    """
    topic = request.topic
    is_python_loop = topic.lower() in PYTHON_LOOP_TOPICS

    if is_python_loop:
        templates = {
            "en": _python_loop_templates_en,
            "hi": _python_loop_templates_hi,
            "kn": _python_loop_templates_kn,
        }[request.language](topic)
    elif FRACTION_TOPIC.search(topic) and not (
        request.language == "hi" and fallback_reason == "translation_unavailable"
    ):
        templates = _fraction_templates_en(topic)
    elif PHOTOSYNTHESIS_TOPIC.search(topic) and not (
        request.language == "hi" and fallback_reason == "translation_unavailable"
    ):
        templates = _photosynthesis_templates_en(topic)
    else:
        # The Kannada fallback reuses English text; translation normally runs
        # first, and the render-time script check still guards that path.
        templates = {
            "en": _generic_templates_en,
            "hi": _generic_templates_hi,
            "kn": _generic_templates_en,
        }[request.language](topic)

    scenes, grow_pool = _build_scenes_from_templates(
        request.language, templates, request.duration_seconds
    )
    lesson = Lesson(
        id=uuid4().hex[:12],
        topic=topic,
        level=request.level,
        language=request.language,
        target_duration_seconds=request.duration_seconds,
        scenes=scenes,
        source="sample",
        fallback=fallback_reason is not None,
        fallback_reason=fallback_reason,
    )
    return lesson, grow_pool


def build_sample_lesson(
    request: LessonRequest,
    *,
    fallback_reason: FallbackReason | None = None,
) -> Lesson:
    """Deterministic fallback lesson with narration sized to the target duration."""
    lesson, _ = build_sample_lesson_with_pool(request, fallback_reason=fallback_reason)
    return lesson
