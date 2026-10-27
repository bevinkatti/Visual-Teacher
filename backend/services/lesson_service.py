from uuid import uuid4

from backend.schemas import CodeExecutionData, FallbackReason, Lesson, LessonRequest, Scene


def build_sample_lesson(
    request: LessonRequest,
    *,
    fallback_reason: FallbackReason | None = None,
) -> Lesson:
    topic = request.topic
    is_python_loop = topic.lower() in {
        "how python code works",
        "python",
        "how does a python loop work?",
        "how does a python loop work",
        "python loops",
        "how python for-loops work",
        "how python for loops work",
        "how do python for loops work",
    }

    if request.language == "hi" and is_python_loop:
        scenes = [
            Scene(
                title="हर सूची वस्तु की एक बारी",
                narration="फ़ॉर लूप सूची से एक वस्तु लेता है, निर्देश चलाता है, फिर अगली वस्तु पर जाता है। हम तीन फलों को देखेंगे।",
                caption="फ़ॉर लूप सूची की हर वस्तु को एक बारी देता है।",
                visual_type="concept_diagram",
                visual_data={"left": "तीन फल", "right": "एक प्रिंट निर्देश", "relationship": "हर फल पर एक बार"},
            ),
            Scene(
                title="हर चक्र में बदलता मान",
                narration="पायथन पहले लूप की पंक्ति पढ़ता है। वह fruit में apple रखता है, फिर print चलाता है। आउटपुट में apple जुड़ता है। अगली बार fruit का मान pear, फिर plum होता है। हर चक्र में वही निर्देश चलता है और आउटपुट बढ़ता है।",
                caption="हर चक्र में fruit बदलता है और आउटपुट में एक पंक्ति जुड़ती है।",
                visual_type="code_execution",
                visual_data={"purpose": "हर सूची वस्तु के लिए एक चक्र।"},
                execution_data=CodeExecutionData(
                    variable_name="fruit",
                    iterable_name="fruits",
                    values=["apple", "pear", "plum"],
                ),
            ),
            Scene(
                title="अगली वस्तु न हो तो लूप रुकता है",
                narration="जब सूची में अगली वस्तु नहीं बचती, पायथन लूप से बाहर आ जाता है। तीन वस्तुओं से आउटपुट की तीन पंक्तियाँ बनीं। फ़ॉर लूप निर्देश को तीन बार लिखे बिना दोहराता है।",
                caption="तीन वस्तुएँ, तीन पंक्तियाँ; अगली वस्तु नहीं तो लूप बंद।",
                visual_type="concept_diagram",
                visual_data={"left": "तीन चक्र", "right": "तीन पंक्तियाँ", "relationship": "अगली वस्तु नहीं → रुकें"},
            ),
        ]
    elif request.language == "hi":
        scenes = [
            Scene(
                title="मुख्य विचार से शुरुआत",
                narration=f"आइए “{topic}” को छोटे चरणों में समझें। पहले मुख्य विचार पहचानें और देखें कि यह किस प्रश्न का उत्तर देता है।",
                caption=f"मुख्य विचार: {topic}",
                visual_type="concept_diagram",
                visual_data={"left": "मुख्य विचार", "right": "समझ", "relationship": "विचार से अर्थ तक"},
            ),
            Scene(
                title="इसे छोटे चरणों में बाँटें",
                narration=f"अब “{topic}” को छोटे भागों में बाँटें। एक समय में एक भाग देखने से पूरा विचार समझना आसान होता है।",
                caption="बड़े विचार को छोटे चरणों में समझें।",
                visual_type="process_flow",
                visual_data={"input": "देखें", "process": "समझें", "output": "समझाएँ"},
            ),
            Scene(
                title="अपनी समझ जाँचें",
                narration=f"अब “{topic}” को अपने शब्दों में समझाएँ। इसे एक ठोस उदाहरण से जोड़ें और देखें कि आप किस भाग को स्पष्ट रूप से बता सकते हैं।",
                caption="अपने शब्दों में उदाहरण सहित समझाएँ।",
                visual_type="concept_diagram",
                visual_data={"left": "उदाहरण", "right": "समझ", "relationship": "समझ को जाँचें"},
            ),
        ]
    elif is_python_loop:
        scenes = [
            Scene(
                title="One turn for every item",
                narration=(
                    "A for loop takes one item from a list, runs an instruction, then "
                    "moves to the next item. We will follow three fruits."
                ),
                caption="A for loop gives each list item one turn.",
                visual_type="concept_diagram",
                visual_data={
                    "left": "3 fruit items",
                    "right": "one print instruction",
                    "relationship": "one pass for each item",
                },
            ),
            Scene(
                title="Watch each pass update the output",
                narration=(
                    "Python reads the loop line first. It assigns apple to fruit, then "
                    "runs print. The output gains apple. Next, fruit becomes pear, and "
                    "then plum. The same instruction runs once for each value, and the "
                    "output grows after every pass."
                ),
                caption="fruit changes on each pass; output grows one line at a time.",
                visual_type="code_execution",
                visual_data={"purpose": "One iteration per list item."},
                execution_data=CodeExecutionData(
                    variable_name="fruit",
                    iterable_name="fruits",
                    values=["apple", "pear", "plum"],
                ),
            ),
            Scene(
                title="No next value means the loop stops",
                narration=(
                    "When the list has no next value, Python leaves the loop. Three "
                    "items produced three output lines. A for loop repeats the "
                    "instruction without copying it three times."
                ),
                caption="Three items produce three lines; no next item means stop.",
                visual_type="concept_diagram",
                visual_data={
                    "left": "3 passes",
                    "right": "3 output lines",
                    "relationship": "no next item → stop",
                },
            ),
        ]
    else:
        scenes = [
            Scene(
                title=f"Start with the idea",
                narration=f"Let's explore {topic}. First, identify the main idea and what problem it helps us understand.",
                caption=f"The central idea: {topic}",
                visual_type="concept",
                visual_data={"left": "The idea", "right": "Understanding"},
            ),
            Scene(
                title="Break it into steps",
                narration=f"Next, break {topic} into smaller parts. Looking at one part at a time makes the overall concept easier to understand.",
                caption="Break a complex idea into smaller parts.",
                visual_type="flow",
                visual_data={"input": "Observe", "process": "Understand", "output": "Explain"},
            ),
            Scene(
                title="Check your understanding",
                narration=f"Now explain {topic} in your own words. Connect the main idea to a concrete example, and check which part you can explain confidently.",
                caption="Explain it in your own words.",
                visual_type="concept",
                visual_data={"left": "Example", "right": "Understanding"},
            ),
        ]

    return Lesson(
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
