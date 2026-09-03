import { createI18n } from 'vue-i18n'

import en from './locales/en.json'

export type MessageSchema = typeof en

export const i18n = createI18n<[MessageSchema], 'en'>({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: { en },
})
