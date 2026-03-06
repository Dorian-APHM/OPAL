import { Select } from 'antd';
import { useTranslation } from 'react-i18next';

interface Props {
  domains: string[];
  value: string | null;
  onChange: (domain: string) => void;
}

export default function DomainSelector({ domains, value, onChange }: Props) {
  const { t } = useTranslation();

  return (
    <Select
      placeholder={t('quality.select_domain')}
      value={value || undefined}
      onChange={onChange}
      style={{ width: '100%' }}
      options={domains.map((d) => ({
        value: d,
        label: t(`domains.${d}`, d),
      }))}
      allowClear
    />
  );
}
