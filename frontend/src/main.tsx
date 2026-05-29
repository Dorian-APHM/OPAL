import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import App from './App';
import { AuthProvider } from './auth/KeycloakContext';
import { ToastProvider } from './components/ui/Toast';
import './i18n';
import './landing.css';
import './opal-theme.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        {/* Respect the user's prefers-reduced-motion setting across all Framer Motion animations */}
        <MotionConfig reducedMotion="user">
          <ToastProvider>
            <App />
          </ToastProvider>
        </MotionConfig>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>
);
