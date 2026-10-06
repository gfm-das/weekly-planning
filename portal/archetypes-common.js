/*
 * archetypes-common.js: small helpers shared by archetypes.html (Archetypal Health) and archetype-settings.html (its
 * Settings). They are on window.Archetypes.
 *
 * Every visible text comes from the portal catalog (portal/i18n/en.json and the other languages, keys archetypes.*)
 * through i18n.js; t() finds a text by key, tr() translates a text that came from the server or the settings.
 */
(() => {
  'use strict';
  const ARCHETYPES = ['finding', 'teaching', 'bringing', 'baptizing', 'fellowshipping', 'reactivating'];

  // A catalog text by key, with {placeholders} filled in. i18n.js falls back to English for a missing translation.
  function t(key, values = {}) {
    const i18n = window.MissionI18n;
    return i18n?.state?.loaded ? i18n.t(key, values) : key;
  }

  // A text written in the settings or sent by the server (a number's name, a diagnosis text, a message): translated
  // while it is still the catalog's English text, shown as written once a manager has changed it.
  function tr(text) {
    const i18n = window.MissionI18n;
    return i18n?.state?.loaded ? i18n.translate(String(text ?? '')) : String(text ?? '');
  }

  function archetypeName(key) {
    return key ? t('archetypes.name.' + key) : '';
  }

  // The band an index falls in (bands are highest first; the last one has no start). Rounded first, so the colour
  // always matches the number people see.
  function bandFor(index, bands) {
    if (index === null || index === undefined) return null;
    const value = Math.round(index);
    return bands.find((band) => band.from === null || value >= band.from) || bands[bands.length - 1];
  }

  // Dark or white text, whichever is easier to read on this background colour (WCAG relative luminance).
  function textOn(hex) {
    const channel = (i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const light = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
    return (light + 0.05) / 0.05 > 1.05 / (light + 0.05) ? '#10252e' : '#ffffff';
  }

  // "120 and above", "110–119", "Below 80" for the legend.
  function bandRange(bands, i) {
    const band = bands[i];
    if (i === 0) return t('archetypes.bandFrom', { from: band.from });
    if (band.from === null) return t('archetypes.bandBelow', { to: bands[i - 1].from });
    return t('archetypes.bandRange', { from: band.from, to: bands[i - 1].from - 1 });
  }

  // "20 Sep 2026" in the chosen language (a week is named by its Sunday).
  function weekDate(iso) {
    const i18n = window.MissionI18n;
    const options = { day: 'numeric', month: 'short', year: 'numeric', timeZone: (window.GFM_SITE && window.GFM_SITE.timeZone) || 'Europe/Berlin' };
    const day = new Date(iso + 'T12:00:00Z');
    return i18n?.date ? i18n.date(day, options) : day.toLocaleDateString(undefined, options);
  }

  function escape(value) {
    return window.escapeHTML ? window.escapeHTML(value) : String(value ?? '');
  }

  // Waits for the catalog (or its failure), so the first drawing is already in the right language.
  function whenReady() {
    return window.MissionI18n?.ready || Promise.resolve();
  }

  window.Archetypes = { ARCHETYPES, t, tr, archetypeName, bandFor, textOn, bandRange, weekDate, escape, whenReady };
})();
