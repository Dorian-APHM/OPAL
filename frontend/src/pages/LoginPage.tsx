import { useState } from 'react';
import { LogIn, UserPlus, IdCard, CheckCircle } from 'lucide-react';
import { publicApi } from '../api/client';
import { Card, Button, Input, Select, Tabs, useToast } from '../components/ui';

interface LoginPageProps {
  onSignIn: () => void;
}

const ROLES = [
  { value: 'chercheur', label: 'Chercheur', description: 'Quality, Cohorts, Concepts' },
  { value: 'medecin', label: 'Medecin', description: 'Mapping, Cohorts, Concepts' },
  { value: 'data-manager', label: 'OMOP DIM', description: 'Full access' },
  { value: 'admin', label: 'Admin', description: 'Full access + administration' },
];

export default function LoginPage({ onSignIn }: LoginPageProps) {
  const [activeTab, setActiveTab] = useState('signin');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [username, setUsername] = useState('');
  const [role, setRole] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const toast = useToast();

  const handleSignUp = async () => {
    const errs: Record<string, string> = {};
    if (!username) errs.username = 'Identifiant requis';
    else if (!/^[a-zA-Z0-9._-]+$/.test(username)) errs.username = 'Lettres, chiffres, . - _ uniquement';
    if (!role) errs.role = 'Choisissez un rôle';
    setErrors(errs);
    if (Object.keys(errs).length) return;

    setLoading(true);
    try {
      await publicApi.submitAccessRequest({ username, requested_role: role! });
      setSubmitted(true);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to submit request');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-deep-base relative overflow-hidden">
      {/* Background pattern — dot grid */}
      <div className="fixed inset-0 pointer-events-none opacity-[0.04]" style={{
        backgroundImage: 'radial-gradient(circle, currentColor 1px, transparent 1px)',
        backgroundSize: '24px 24px',
      }} />
      {/* Background glow — primary emerald */}
      <div className="fixed top-[25%] left-1/2 w-[90vw] max-w-[700px] h-[500px] -translate-x-1/2 -translate-y-1/2 bg-[radial-gradient(ellipse,rgba(16,185,129,0.15)_0%,transparent_65%)] pointer-events-none" />
      {/* Background glow — secondary blue */}
      <div className="fixed bottom-[5%] right-[5%] w-[400px] h-[400px] bg-[radial-gradient(ellipse,rgba(59,130,246,0.08)_0%,transparent_65%)] pointer-events-none" />
      {/* Background glow — tertiary teal top-left */}
      <div className="fixed top-[10%] left-[5%] w-[300px] h-[300px] bg-[radial-gradient(ellipse,rgba(20,184,166,0.06)_0%,transparent_65%)] pointer-events-none" />

      <Card className="w-full max-w-[460px] mx-4 opal-card-accent" hoverable={false}>
        <div className="text-center mb-6">
          <div className="relative inline-block mb-3">
            <img src="/opal-logo.svg" alt="OPAL" className="h-24 mx-auto drop-shadow-[0_0_20px_rgba(16,185,129,0.3)]" />
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-20 h-20 bg-emerald-accent/15 rounded-full blur-2xl" />
          </div>
          <p className="text-text-muted text-sm tracking-wide">OMOP Platform for Analytics & Lineage</p>
        </div>

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'signin',
              label: <span className="flex items-center gap-1.5"><LogIn className="h-4 w-4" /> Sign In</span>,
              children: (
                <div className="text-center py-6">
                  <p className="text-sm text-text-muted mb-6">Connectez-vous avec votre compte OPAL</p>
                  <Button variant="primary" size="large" icon={<LogIn className="h-5 w-5" />} onClick={onSignIn} block>
                    Se connecter via Keycloak
                  </Button>
                </div>
              ),
            },
            {
              key: 'signup',
              label: <span className="flex items-center gap-1.5"><UserPlus className="h-4 w-4" /> Sign Up</span>,
              children: submitted ? (
                <div className="text-center py-8">
                  <CheckCircle className="h-12 w-12 text-emerald-accent mx-auto mb-4" />
                  <h3 className="text-lg font-semibold text-text-bright mb-2">Demande envoyée</h3>
                  <p className="text-sm text-text-muted">
                    Votre demande d'accès a été soumise. Un administrateur va la valider.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <Input
                    label="Identifiant"
                    prefix={<IdCard className="h-4 w-4" />}
                    placeholder="ex: jdupont"
                    value={username}
                    onChange={(e) => { setUsername(e.target.value); setErrors((prev) => ({ ...prev, username: '' })); }}
                    error={errors.username}
                    required
                  />
                  <div>
                    <Select
                      label="Rôle demandé *"
                      placeholder="Choisir un rôle"
                      value={role}
                      onChange={(v) => { setRole(v); setErrors((prev) => ({ ...prev, role: '' })); }}
                      options={ROLES}
                    />
                    {errors.role && <p className="text-xs text-red-400 mt-1">{errors.role}</p>}
                  </div>
                  <Button variant="primary" size="large" icon={<UserPlus className="h-5 w-5" />} onClick={handleSignUp} loading={loading} block>
                    Demander l'accès
                  </Button>
                  <p className="text-xs text-text-dim text-center">
                    Utilisez votre identifiant professionnel. Vous vous connecterez avec vos identifiants une fois approuvé.
                  </p>
                </div>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
