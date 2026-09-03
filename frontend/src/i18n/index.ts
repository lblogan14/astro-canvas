import { createI18n } from 'vue-i18n'

import en from './locales/en.json'
import enAutoform from './locales/en.autoform.json'

/** English messages are split by feature area and merged here (all keys are top-level groups). */
const messages = { ...en, ...enAutoform }

export type MessageSchema = typeof messages

export const i18n = createI18n<[MessageSchema], 'en'>({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: { en: messages },
  datetimeFormats: {
    en: {
      short: {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      },
    },
  },
  numberFormats: {
    en: { decimal: { style: 'decimal', maximumFractionDigits: 2 } },
  },
})
