import { useTranslation } from 'react-i18next';
import { Select } from '../ui';

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
      className="w-full"
      options={domains.map((d) => ({
        value: d,
        label: t(`domains.${d}`, d),
      }))}
      allowClear
    />
  );
}
