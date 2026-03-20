import { createContext, useContext, useEffect, useState, useCallback, useRef, type ReactNode } from 'react';
import Keycloak from 'keycloak-js';
import { setTokenGetter } from '../api/client';

// Role definitions matching permissions.yaml
export type OpalRole = 'admin' | 'data-manager' | 'chercheur' | 'medecin';

/** Permissions fetched from /api/auth/permissions (driven by permissions.yaml) */
interface Permissions {
  roles: string[];
  pages: string[] | 'all';
  cdm_visibility: 'all' | 'acl_only';
  can_manage_access: boolean;
  can_clear_all_grants: boolean;
}

interface AuthContextType {
  authenticated: boolean;
  initialized: boolean;
  username: string;
  roles: OpalRole[];
  token: string | undefined;
  permissions: Permissions | null;
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
  permissions: null,
  login: () => {},
  logout: () => {},
  hasPageAccess: () => false,
});

export const useAuth = () => useContext(AuthContext);

// Determine Keycloak URL based on browser location
function getKeycloakUrl(): string {
  const hostname = window.location.hostname;
  const protocol = window.location.protocol;
  const port = protocol === 'https:' ? '8443' : '8080';
  return `${protocol}//${hostname}:${port}`;
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
    ['admin', 'data-manager', 'chercheur', 'medecin'].includes(r)
  );
}

// Dev mode: skip Keycloak entirely when VITE_AUTH_DISABLED is set
const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === 'true';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(AUTH_DISABLED);
  const [initialized, setInitialized] = useState(AUTH_DISABLED);
  const [username, setUsername] = useState(AUTH_DISABLED ? 'dev-user' : '');
  const [roles, setRoles] = useState<OpalRole[]>(AUTH_DISABLED ? ['admin'] : []);
  const [token, setToken] = useState<string | undefined>(AUTH_DISABLED ? 'dev-token' : undefined);
  const [permissions, setPermissions] = useState<Permissions | null>(
    AUTH_DISABLED ? { roles: ['admin'], pages: 'all', cdm_visibility: 'all', can_manage_access: true, can_clear_all_grants: true } : null
  );
  const permsFetched = useRef(AUTH_DISABLED);

  // Fetch permissions from backend (driven by permissions.yaml)
  const fetchPermissions = useCallback(async (tkn: string) => {
    if (permsFetched.current) return;
    permsFetched.current = true;
    try {
      const res = await fetch('/api/auth/permissions', {
        headers: { Authorization: `Bearer ${tkn}` },
      });
      if (res.ok) {
        const data: Permissions = await res.json();
        setPermissions(data);
      }
    } catch {
      // Fallback: permissions will be null, hasPageAccess falls back to role-based
    }
  }, []);

  const applyAuth = useCallback(() => {
    setTokenGetter(() => keycloak.token);
    setToken(keycloak.token);
    setAuthenticated(true);
    setUsername(keycloak.tokenParsed?.preferred_username || '');
    setRoles(extractRoles(keycloak.tokenParsed));
    if (keycloak.token) {
      fetchPermissions(keycloak.token);
    }
  }, [fetchPermissions]);

  useEffect(() => {
    if (AUTH_DISABLED) return; // Skip Keycloak init in dev mode
    let cancelled = false;

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
    import('../hooks/useSessionState').then(m => m.clearSessionState()).catch(() => {});
    keycloak.logout({ redirectUri: window.location.origin });
  }, []);

  const hasPageAccess = useCallback(
    (path: string): boolean => {
      // Use permissions from API if available (single source of truth)
      if (permissions) {
        if (permissions.pages === 'all') return true;
        return permissions.pages.some((p) =>
          p === '/' ? path === '/' : path.startsWith(p)
        );
      }
      // Fallback: no access until permissions are loaded (brief moment)
      return roles.length > 0 && roles.some(r => r === 'admin' || r === 'data-manager');
    },
    [permissions, roles]
  );

  return (
    <AuthContext.Provider
      value={{ authenticated, initialized, username, roles, token, permissions, login, logout, hasPageAccess }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export { keycloak };
