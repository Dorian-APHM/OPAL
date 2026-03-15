import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import fr from './fr.json';
import en from './en.json';

i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: localStorage.getItem('opal-lang') || 'fr',
  fallbackLng: 'fr',
  interpolation: {
    escapeValue: true,
  },
});

export default i18n;
