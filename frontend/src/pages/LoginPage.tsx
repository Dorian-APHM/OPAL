import { useState } from 'react';
import {
  Card, Tabs, Button, Form, Input, Select, Result, Typography, Space, message,
} from 'antd';
import {
  LoginOutlined, UserAddOutlined, MailOutlined, UserOutlined, IdcardOutlined,
} from '@ant-design/icons';
import { publicApi } from '../api/client';

const { Title, Text, Paragraph } = Typography;

interface LoginPageProps {
  onSignIn: () => void;
}

const ROLES = [
  { value: 'chercheur', label: 'Chercheur', description: 'Quality, Cohorts, Concepts' },
  { value: 'medecin', label: 'Medecin', description: 'Mapping, Cohorts, Concepts' },
  { value: 'omop-dim', label: 'OMOP DIM', description: 'Full access' },
  { value: 'admin', label: 'Admin', description: 'Full access + administration' },
];

export default function LoginPage({ onSignIn }: LoginPageProps) {
  const [activeTab, setActiveTab] = useState('signin');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const handleSignUp = async (values: any) => {
    setLoading(true);
    try {
      await publicApi.submitAccessRequest({
        username: values.username,
        email: values.email,
        first_name: values.first_name,
        last_name: values.last_name,
        requested_role: values.requested_role,
      });
      setSubmitted(true);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Failed to submit request';
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      minHeight: '100vh', background: 'linear-gradient(135deg, #1f77b4 0%, #0d4f7a 100%)',
    }}>
      <Card
        style={{ width: 460, borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.2)' }}
        bodyStyle={{ padding: '32px 32px 24px' }}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ margin: 0, color: '#1f77b4' }}>OPAL</Title>
          <Text type="secondary">OMOP Platform for Analytics & Lineage</Text>
        </div>

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          centered
          items={[
            {
              key: 'signin',
              label: <span><LoginOutlined /> Sign In</span>,
              children: (
                <div style={{ textAlign: 'center', padding: '24px 0' }}>
                  <Paragraph type="secondary" style={{ marginBottom: 24 }}>
                    Connectez-vous avec votre compte OPAL
                  </Paragraph>
                  <Button
                    type="primary"
                    size="large"
                    icon={<LoginOutlined />}
                    onClick={onSignIn}
                    block
                    style={{ height: 48 }}
                  >
                    Se connecter via Keycloak
                  </Button>
                </div>
              ),
            },
            {
              key: 'signup',
              label: <span><UserAddOutlined /> Sign Up</span>,
              children: submitted ? (
                <Result
                  status="success"
                  title="Demande envoyee"
                  subTitle="Votre demande d'acces a ete soumise. Un administrateur va la valider. Vous recevrez vos identifiants une fois approuve."
                />
              ) : (
                <Form
                  form={form}
                  layout="vertical"
                  onFinish={handleSignUp}
                  size="middle"
                  requiredMark={false}
                >
                  <Form.Item
                    name="username"
                    label="Identifiant"
                    rules={[
                      { required: true, message: 'Identifiant requis' },
                      { pattern: /^[a-zA-Z0-9._-]+$/, message: 'Lettres, chiffres, . - _ uniquement' },
                    ]}
                  >
                    <Input prefix={<IdcardOutlined />} placeholder="ex: jdupont" />
                  </Form.Item>

                  <Form.Item
                    name="email"
                    label="Email"
                    rules={[
                      { required: true, message: 'Email requis' },
                      { type: 'email', message: 'Email invalide' },
                    ]}
                  >
                    <Input prefix={<MailOutlined />} placeholder="jean.dupont@hopital.fr" />
                  </Form.Item>

                  <Space style={{ display: 'flex' }} size={12}>
                    <Form.Item
                      name="first_name"
                      label="Prenom"
                      rules={[{ required: true, message: 'Requis' }]}
                      style={{ flex: 1 }}
                    >
                      <Input prefix={<UserOutlined />} placeholder="Jean" />
                    </Form.Item>

                    <Form.Item
                      name="last_name"
                      label="Nom"
                      rules={[{ required: true, message: 'Requis' }]}
                      style={{ flex: 1 }}
                    >
                      <Input placeholder="Dupont" />
                    </Form.Item>
                  </Space>

                  <Form.Item
                    name="requested_role"
                    label="Role demande"
                    rules={[{ required: true, message: 'Choisissez un role' }]}
                  >
                    <Select placeholder="Choisir un role">
                      {ROLES.map(r => (
                        <Select.Option key={r.value} value={r.value}>
                          <Space>
                            <strong>{r.label}</strong>
                            <Text type="secondary" style={{ fontSize: 12 }}>— {r.description}</Text>
                          </Space>
                        </Select.Option>
                      ))}
                    </Select>
                  </Form.Item>

                  <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={loading}
                      block
                      size="large"
                      icon={<UserAddOutlined />}
                      style={{ height: 48 }}
                    >
                      Demander l'acces
                    </Button>
                  </Form.Item>

                  <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, textAlign: 'center' }}>
                    Votre mot de passe initial sera votre identifiant.
                    Il vous sera demande de le changer a la premiere connexion.
                  </Paragraph>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
