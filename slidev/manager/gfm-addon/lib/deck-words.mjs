// The few words the deck components show to the audience (lists and charts), in the 14 languages of the portal.
// The language is the deck's (`<html lang>`, set by the deck's `lang` frontmatter) or else the browser's. Pure JavaScript.

export const WORDS = {
  en: { loading: 'Loading mission numbers…', sample: 'Sample numbers: the live numbers are not available here.', empty: 'Nothing to list yet.', page: 'Page {n} of {m}', more: '{n} more not shown' },
  de: { loading: 'Missionszahlen werden geladen…', sample: 'Beispielzahlen: Die Live-Zahlen sind hier nicht verfügbar.', empty: 'Noch nichts aufzulisten.', page: 'Seite {n} von {m}', more: '{n} weitere nicht gezeigt' },
  fr: { loading: 'Chargement des chiffres de la mission…', sample: 'Chiffres d’exemple : les chiffres en direct ne sont pas disponibles ici.', empty: 'Rien à afficher pour l’instant.', page: 'Page {n} sur {m}', more: '{n} de plus non affichés' },
  es: { loading: 'Cargando las cifras de la misión…', sample: 'Cifras de ejemplo: las cifras en vivo no están disponibles aquí.', empty: 'Todavía no hay nada que mostrar.', page: 'Página {n} de {m}', more: '{n} más sin mostrar' },
  it: { loading: 'Caricamento dei numeri della missione…', sample: 'Numeri di esempio: i numeri in tempo reale non sono disponibili qui.', empty: 'Ancora niente da elencare.', page: 'Pagina {n} di {m}', more: 'altri {n} non mostrati' },
  pt: { loading: 'Carregando os números da missão…', sample: 'Números de exemplo: os números ao vivo não estão disponíveis aqui.', empty: 'Ainda não há nada para listar.', page: 'Página {n} de {m}', more: 'mais {n} não mostrados' },
  ro: { loading: 'Se încarcă cifrele misiunii…', sample: 'Cifre de exemplu: cifrele în timp real nu sunt disponibile aici.', empty: 'Încă nimic de afișat.', page: 'Pagina {n} din {m}', more: 'încă {n} neafișate' },
  ru: { loading: 'Загрузка показателей миссии…', sample: 'Пример: актуальные данные здесь недоступны.', empty: 'Пока нечего показать.', page: 'Страница {n} из {m}', more: 'ещё {n} не показано' },
  uk: { loading: 'Завантаження показників місії…', sample: 'Приклад: актуальні дані тут недоступні.', empty: 'Поки що нічого показати.', page: 'Сторінка {n} з {m}', more: 'ще {n} не показано' },
  sv: { loading: 'Missionens siffror laddas…', sample: 'Exempelsiffror: de aktuella siffrorna finns inte här.', empty: 'Inget att visa än.', page: 'Sida {n} av {m}', more: '{n} till visas inte' },
  da: { loading: 'Missionens tal indlæses…', sample: 'Eksempeltal: de aktuelle tal er ikke tilgængelige her.', empty: 'Intet at vise endnu.', page: 'Side {n} af {m}', more: '{n} mere vises ikke' },
  tr: { loading: 'Misyon rakamları yükleniyor…', sample: 'Örnek rakamlar: canlı rakamlar burada kullanılamıyor.', empty: 'Henüz listelenecek bir şey yok.', page: 'Sayfa {n} / {m}', more: '{n} tane daha gösterilmiyor' },
  ar: { loading: 'جارٍ تحميل أرقام البعثة…', sample: 'أرقام نموذجية: الأرقام المباشرة غير متاحة هنا.', empty: 'لا يوجد شيء لعرضه بعد.', page: 'الصفحة {n} من {m}', more: '{n} أخرى غير معروضة' },
  fa: { loading: 'در حال بارگیری آمار مأموریت…', sample: 'اعداد نمونه: آمار زنده اینجا در دسترس نیست.', empty: 'هنوز چیزی برای نمایش نیست.', page: 'صفحه {n} از {m}', more: '{n} مورد دیگر نمایش داده نشده' },
}

/** The language code to use: the first of `candidates` (like 'de-DE') that has words, else English. */
export function deckLanguage(candidates = []) {
  for (const c of candidates) {
    const code = String(c || '').toLowerCase().split(/[-_]/)[0]
    if (WORDS[code]) return code
  }
  return 'en'
}

/** One word in a language, with {n} and {m} filled in. */
export function word(lang, key, vars = {}) {
  const text = (WORDS[lang] || WORDS.en)[key] ?? WORDS.en[key] ?? key
  return text.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ''))
}

/** The deck's language in the browser. */
export function pageLanguage() {
  if (typeof document === 'undefined') return 'en'
  return deckLanguage([document.documentElement.lang, ...(typeof navigator !== 'undefined' ? navigator.languages || [navigator.language] : [])])
}
