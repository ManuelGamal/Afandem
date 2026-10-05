"""Scripted customer turns for the demo button, the replay recording and the video.
Played in order from a fresh sandbox, so replay keys line up."""

DEMO_SCRIPTS = [
    {"title": "بيع كامل في الشات", "conversation_id": "demo-sale", "steps": [
        {"say": "السلام عليكم، الهودي التقيل بكام؟"},
        {"say": "طولي 178 ووزني 80 وبحب اللبس واسع شوية"},
        {"say": "تمام هاخد الأسود"},
        {"say": "اسمي كريم عادل 01098765432، 14 شارع الطيران الدور 4 شقة 8، مدينة نصر"},
        {"say": "تمام"},
    ]},
    {"title": "Arabizi", "conversation_id": "demo-arabizi", "steps": [
        {"say": "3ayez jeans slim size 32 eswed, bekam?"},
        {"say": "w el delivery le el maadi kam?"},
    ]},
    {"title": "تأكيد طلب الموقع: عنوان ناقص ومعاد جديد", "conversation_id": None, "steps": [
        {"checkout": 1},
        {"say": "ايوه انا. العنوان عمارة 7 جنب سوبر ماركت خير زمان، الدور التالت"},
        {"say": "بس بكره مش هكون موجودة، ينفع بعد بكره؟"},
        {"say": "تمام"},
    ]},
    {"title": "عميل بيلغي قبل الشحن", "conversation_id": None, "steps": [
        {"checkout": 2},
        {"say": "لا معلش أنا غيرت رأيي، الغيه"},
    ]},
    {"title": "طلب عالي المخاطرة", "conversation_id": None, "steps": [
        {"checkout": 3},
        {"say": "اه اكد"},
    ]},
    {"title": "شكوى ← موظف", "conversation_id": "demo-complaint", "steps": [
        {"say": "التيشيرت اللي جالي امبارح مقطوع وعايز فلوسي"},
    ]},
    {"title": "عميل مبيردش", "conversation_id": None, "steps": [
        {"checkout": 4},
        {"advance": 2},
        {"advance": 2},
    ]},
]
