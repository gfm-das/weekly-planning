"""The words of push reminders, in the portal's 14 interface languages.

What it is: a small dictionary of texts and two helpers (language_code, text).
Who uses it: reminders.py, when it sends the Sunday planning reminder and meeting reminders.
How it fits: a reminder reaches a phone without a page around it, so the server writes it in the person's language:
the one they chose in the portal (portal.user_preferences), else their primary language from DA Management, else
the mission's default language (missions.default_language, English unless the mission chose another). The keys and texts
are the same as push.* in portal/i18n/<code>.json; tests/test_push_texts.py checks that they stay the same. Every language but English needs review by a native speaker.
"""

TEXTS = {
    'en': {'push.planningDueTitle': 'Weekly Planning is due',
           'push.planningDueBody': 'Submit your companionship’s plan for the coming week.',
           'push.meetingNow': 'Your mission meeting starts now.',
           'push.meetingSoon': 'Your mission meeting starts soon.'},
    'de': {'push.planningDueTitle': 'Die Wochenplanung ist fällig',
           'push.planningDueBody': 'Reicht den Plan eurer Mitarbeiterschaft für die kommende Woche ein.',
           'push.meetingNow': 'Deine Missionsversammlung beginnt jetzt.',
           'push.meetingSoon': 'Deine Missionsversammlung beginnt bald.'},
    'es': {'push.planningDueTitle': 'Es hora de la planificación semanal',
           'push.planningDueBody': 'Envíen el plan de su compañerismo para la próxima semana.',
           'push.meetingNow': 'Tu reunión de la misión comienza ahora.',
           'push.meetingSoon': 'Tu reunión de la misión comienza pronto.'},
    'fr': {'push.planningDueTitle': 'La planification hebdomadaire est à faire',
           'push.planningDueBody': 'Soumettez le plan de votre équipe pour la semaine qui vient.',
           'push.meetingNow': 'Votre réunion de mission commence maintenant.',
           'push.meetingSoon': 'Votre réunion de mission commence bientôt.'},
    'pt': {'push.planningDueTitle': 'Hora do planejamento semanal',
           'push.planningDueBody': 'Enviem o plano da sua dupla para a próxima semana.',
           'push.meetingNow': 'Sua reunião da missão começa agora.',
           'push.meetingSoon': 'Sua reunião da missão começa em breve.'},
    'uk': {'push.planningDueTitle': 'Час для щотижневого планування',
           'push.planningDueBody': 'Надішліть план вашої пари на наступний тиждень.',
           'push.meetingNow': 'Ваші збори місії починаються зараз.',
           'push.meetingSoon': 'Ваші збори місії скоро почнуться.'},
    'ru': {'push.planningDueTitle': 'Пора заняться еженедельным планированием',
           'push.planningDueBody': 'Отправьте план вашей пары на следующую неделю.',
           'push.meetingNow': 'Ваше собрание миссии начинается сейчас.',
           'push.meetingSoon': 'Ваше собрание миссии скоро начнется.'},
    'it': {'push.planningDueTitle': 'È il momento della pianificazione settimanale',
           'push.planningDueBody': 'Inviate il piano della vostra coppia per la prossima settimana.',
           'push.meetingNow': 'La tua riunione di missione inizia ora.',
           'push.meetingSoon': 'La tua riunione di missione inizia presto.'},
    'tr': {'push.planningDueTitle': 'Haftalık Planlama zamanı',
           'push.planningDueBody': 'Yoldaşlığınızın gelecek hafta için planını gönderin.',
           'push.meetingNow': 'Misyon toplantınız şimdi başlıyor.',
           'push.meetingSoon': 'Misyon toplantınız birazdan başlıyor.'},
    'fa': {'push.planningDueTitle': 'وقت برنامه‌ریزی هفتگی است',
           'push.planningDueBody': 'برنامهٔ خودتان و همکارتان را برای هفتهٔ آینده ارسال کنید.',
           'push.meetingNow': 'جلسهٔ مأموریت شما هم‌اکنون آغاز می‌شود.',
           'push.meetingSoon': 'جلسهٔ مأموریت شما به‌زودی آغاز می‌شود.'},
    'ro': {'push.planningDueTitle': 'E timpul pentru planificarea săptămânală',
           'push.planningDueBody': 'Trimiteți planul colegilor de misiune pentru săptămâna care vine.',
           'push.meetingNow': 'Întâlnirea ta din misiune începe acum.',
           'push.meetingSoon': 'Întâlnirea ta din misiune începe în curând.'},
    'sv': {'push.planningDueTitle': 'Dags för veckoplaneringen',
           'push.planningDueBody': 'Skicka in ert kamratskaps plan för den kommande veckan.',
           'push.meetingNow': 'Ditt missionsmöte börjar nu.',
           'push.meetingSoon': 'Ditt missionsmöte börjar snart.'},
    'da': {'push.planningDueTitle': 'Tid til ugentlig planlægning',
           'push.planningDueBody': 'Indsend jeres makkerpars plan for den kommende uge.',
           'push.meetingNow': 'Dit missionsmøde begynder nu.',
           'push.meetingSoon': 'Dit missionsmøde begynder snart.'},
    'ar': {'push.planningDueTitle': 'حان وقت التخطيط الأسبوعي',
           'push.planningDueBody': 'أرسلوا خطة رفقتكم للأسبوع القادم.',
           'push.meetingNow': 'يبدأ اجتماع البعثة الآن.',
           'push.meetingSoon': 'سيبدأ اجتماع البعثة قريبًا.'},
}
# The Church's language codes and other three-letter names that may be stored for a person.
ALIASES = {'eng': 'en', 'deu': 'de', 'ger': 'de', 'spa': 'es', 'fra': 'fr', 'fre': 'fr', 'por': 'pt', 'ukr': 'uk',
           'rus': 'ru', 'ita': 'it', 'tur': 'tr', 'pes': 'fa', 'fas': 'fa', 'per': 'fa', 'ron': 'ro', 'rum': 'ro',
           'swe': 'sv', 'dan': 'da', 'ara': 'ar'}


def language_code(language):
    """The interface language for a stored language (de, de-AT, deu, fa-IR …); English when there is none."""
    base = str(language or 'en').strip().lower().replace('_', '-').split('-')[0]
    base = ALIASES.get(base, base)
    return base if base in TEXTS else 'en'


def text(language, key):
    """The text for key in this language; the English text when the language has none."""
    return TEXTS[language_code(language)].get(key) or TEXTS['en'][key]
