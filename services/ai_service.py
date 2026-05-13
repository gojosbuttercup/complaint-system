from dataclasses import dataclass


DEPARTMENT_BY_CATEGORY = {
    "water": "Water Department",
    "electricity": "Electricity Department",
    "internet": "Internet Department",
    "roads": "Roads Department",
    "sanitation": "Sanitation Department",
    "public_safety": "Public Safety Department",
    "waste_management": "Waste Management Department",
    "other": "Public Safety Department",
}


CATEGORY_KEYWORDS = {
    "water": ["water", "leak", "pipe", "sewer", "drainage", "tap"],
    "electricity": ["electricity", "power", "light", "outage", "transformer", "wire"],
    "internet": ["internet", "wifi", "broadband", "network", "fiber", "connectivity"],
    "roads": ["road", "pothole", "street", "sidewalk", "traffic", "bridge"],
    "sanitation": ["sanitation", "toilet", "hygiene", "dirty", "cleaning"],
    "public_safety": ["safety", "police", "crime", "theft", "accident", "hazard", "danger"],
    "waste_management": ["waste", "garbage", "trash", "rubbish", "dump", "collection"],
}


TRAINING_DATA = [
    ("Water is leaking from a broken main pipe near my house", "water", "high"),
    ("No water supply in the block since morning", "water", "medium"),
    ("Tap water pressure is low this week", "water", "low"),
    ("Power outage in the neighborhood needs immediate attention", "electricity", "high"),
    ("Street light wire is sparking near school", "electricity", "high"),
    ("Electricity voltage keeps fluctuating", "electricity", "medium"),
    ("Internet broadband has been down all day", "internet", "medium"),
    ("Wifi and fiber connection are not working", "internet", "medium"),
    ("Slow internet speed for several days", "internet", "low"),
    ("Large pothole on main road caused an accident", "roads", "high"),
    ("Road surface is damaged and unsafe", "roads", "medium"),
    ("Sidewalk repair is needed near the market", "roads", "low"),
    ("Public toilet is dirty and needs cleaning", "sanitation", "medium"),
    ("Sanitation issue causing bad smell in the area", "sanitation", "medium"),
    ("Drain cleaning has not been done this month", "sanitation", "low"),
    ("Dangerous safety hazard near the intersection", "public_safety", "high"),
    ("Theft reported and police support is needed", "public_safety", "high"),
    ("Broken barrier is a public safety concern", "public_safety", "medium"),
    ("Garbage collection missed for three days", "waste_management", "medium"),
    ("Trash dump is overflowing and urgent", "waste_management", "high"),
    ("Waste bins are full near the park", "waste_management", "low"),
]


@dataclass
class ClassificationResult:
    category: str
    urgency: str
    department: str
    category_confidence: float
    urgency_confidence: float
    source: str


class ComplaintAI:
    def __init__(self):
        self.category_model = None
        self.urgency_model = None
        self.ready = False
        self.load()

    def load(self):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
        except Exception:
            self.ready = False
            return

        texts = [row[0] for row in TRAINING_DATA]
        categories = [row[1] for row in TRAINING_DATA]
        urgencies = [row[2] for row in TRAINING_DATA]

        self.category_model = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2))),
            ("clf", LogisticRegression(max_iter=1000)),
        ])
        self.urgency_model = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2))),
            ("clf", LogisticRegression(max_iter=1000)),
        ])
        self.category_model.fit(texts, categories)
        self.urgency_model.fit(texts, urgencies)
        self.ready = True

    def classify(self, text: str) -> ClassificationResult:
        fallback_category = classify_category_keywords(text)
        fallback_urgency = detect_urgency_keywords(text)

        if not self.ready:
            return self._result(fallback_category, fallback_urgency, 0, 0, "keywords")

        category, category_confidence = self._predict(self.category_model, text)
        urgency, urgency_confidence = self._predict(self.urgency_model, text)

        source = "scikit-learn"
        if category_confidence < 0.33:
            category = fallback_category
            source = "keywords"
        if urgency_confidence < 0.34:
            urgency = fallback_urgency
            source = "keywords"

        return self._result(category, urgency, category_confidence, urgency_confidence, source)

    def _predict(self, model, text: str):
        prediction = model.predict([text])[0]
        confidence = 1.0
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba([text])[0]
            confidence = float(max(probabilities))
        return prediction, confidence

    def _result(self, category, urgency, category_confidence, urgency_confidence, source):
        return ClassificationResult(
            category=category,
            urgency=urgency,
            department=DEPARTMENT_BY_CATEGORY.get(category, "Public Safety Department"),
            category_confidence=category_confidence,
            urgency_confidence=urgency_confidence,
            source=source,
        )


def classify_category_keywords(text: str) -> str:
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(word in text_lower for word in keywords):
            return category
    return "other"


def detect_urgency_keywords(text: str) -> str:
    text_lower = text.lower()
    if any(word in text_lower for word in ["urgent", "immediately", "danger", "sparking", "accident"]):
        return "high"
    if any(word in text_lower for word in ["soon", "several days", "not working", "missed"]):
        return "medium"
    return "low"


ai_classifier = ComplaintAI()
