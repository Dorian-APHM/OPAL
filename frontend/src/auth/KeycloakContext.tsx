import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react';
import Keycloak from 'keycloak-js';
import { setTokenGetter } from '../api/client';

// Role definitions matching backend ROLE_ROUTE_ACCESS
export type OpalRole = 'admin' | 'omop-dim' | 'chercheur' | 'medecin';

// Route access per role (matches backend)
const ROLE_PAGE_ACCESS: Record<OpalRole, string[] | null> = {
  admin: null, // all pages
  'omop-dim': null,
  chercheur: ['/quality', '/cohorts', '/concepts'],
  medecin: ['/mapping', '/cohorts', '/concepts'],
};
// /audit and /users are implicitly admin-only since they're not in chercheur/medecin lists

interface AuthContextType {
  authenticated: boolean;
  initialized: boolean;
  username: string;
  roles: OpalRole[];
  token: string | undefined;
  login: () => void;
  logout: () => void;
  hasPageAccess: (path: string) => boolean;
}

const AuthContext = createContext<AuthContextType>({
  authenticated: false,
  initialized: false,
  username: '',
  roles: [],
  token: undefined,
  login: () => {},
  logout: () => {},
  hasPageAccess: () => false,
});

export const useAuth = () => useContext(AuthContext);

// Determine Keycloak URL based on browser location
function getKeycloakUrl(): string {
  // In production (Docker), Keycloak is on the same host at port 8080
  const hostname = window.location.hostname;
  return `http://${hostname}:8080`;
}

const keycloak = new Keycloak({
  url: getKeycloakUrl(),
  realm: 'opal',
  clientId: 'opal-frontend',
});

function extractRoles(tokenParsed: any): OpalRole[] {
  const tokenRoles: string[] =
    tokenParsed?.roles ||
    tokenParsed?.realm_access?.roles ||
    [];
  return tokenRoles.filter((r): r is OpalRole =>
    ['admin', 'omop-dim', 'chercheur', 'medecin'].includes(r)
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [username, setUsername] = useState('');
  const [roles, setRoles] = useState<OpalRole[]>([]);
  const [token, setToken] = useState<string | undefined>();

  const applyAuth = useCallback(() => {
    setTokenGetter(() => keycloak.token);
    setToken(keycloak.token);
    setAuthenticated(true);
    setUsername(keycloak.tokenParsed?.preferred_username || '');
    setRoles(extractRoles(keycloak.tokenParsed));
  }, []);

  useEffect(() => {
    let cancelled = false;

    // If already authenticated (StrictMode double-mount), just read state
    if (keycloak.authenticated) {
      applyAuth();
      setInitialized(true);
    } else {
      keycloak
        .init({
          onLoad: 'check-sso',
          checkLoginIframe: false,
          pkceMethod: 'S256',
          silentCheckSsoRedirectUri: undefined,
        })
        .then((auth: boolean) => {
          if (cancelled) return;
          if (auth) {
            applyAuth();
          }
          setInitialized(true);
        })
        .catch(() => {
          if (cancelled) return;
          console.error('Keycloak init failed');
          setInitialized(true);
        });
    }

    // Token refresh
    const interval = setInterval(() => {
      if (keycloak.authenticated) {
        keycloak
          .updateToken(30)
          .then((refreshed: boolean) => {
            if (refreshed) {
              setToken(keycloak.token);
            }
          })
          .catch(() => {
            console.warn('Token refresh failed, logging out');
            keycloak.logout();
          });
      }
    }, 30000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [applyAuth]);

  const login = useCallback(() => {
    keycloak.login({ redirectUri: window.location.origin });
  }, []);

  const logout = useCallback(() => {
    keycloak.logout({ redirectUri: window.location.origin });
  }, []);

  const hasPageAccess = useCallback(
    (path: string): boolean => {
      if (roles.length === 0) return false;
      for (const role of roles) {
        const allowed = ROLE_PAGE_ACCESS[role];
        if (allowed === null) return true; // admin/omop-dim
        if (allowed.some((p) => path.startsWith(p))) return true;
      }
      return false;
    },
    [roles]
  );

  return (
    <AuthContext.Provider
      value={{ authenticated, initialized, username, roles, token, login, logout, hasPageAccess }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export { keycloak };
