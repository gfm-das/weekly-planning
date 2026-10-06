/** 'friends_found.actual' -> 'friends_found_actual': the name a formula uses for a measure. */
export const fieldKey = (measure: string) => measure.replace(/\./g, '_');
