import { type ReactNode } from 'react';
import { motion } from 'framer-motion';
import {
  Inbox, Database, Users, FileSearch, Bell, Star,
  BarChart3, GitCompareArrows, Shield, FolderOpen,
} from 'lucide-react';

interface EmptyProps {
  icon?: ReactNode;
  description?: ReactNode;
  title?: string;
  children?: ReactNode;
  /** Predefined illustration variants */
  variant?: 'default' | 'no-data' | 'no-cdm' | 'no-cohorts' | 'no-results' | 'no-notifications' | 'no-favorites' | 'no-quality' | 'no-mapping' | 'no-access' | 'no-files';
  className?: string;
}

const variantConfig: Record<string, { icon: ReactNode; title: string; description: string }> = {
  'default': {
    icon: <Inbox className="h-10 w-10" />,
    title: 'Nothing here yet',
    description: 'No data to display.',
  },
  'no-data': {
    icon: <Database className="h-10 w-10" />,
    title: 'No data available',
    description: 'This section is empty. Data will appear here once available.',
  },
  'no-cdm': {
    icon: <Database className="h-10 w-10" />,
    title: 'No database selected',
    description: 'Select a CDM database from the navigation bar to get started.',
  },
  'no-cohorts': {
    icon: <Users className="h-10 w-10" />,
    title: 'No cohorts yet',
    description: 'Create your first cohort to start building patient populations.',
  },
  'no-results': {
    icon: <FileSearch className="h-10 w-10" />,
    title: 'No results found',
    description: 'Try adjusting your search criteria or filters.',
  },
  'no-notifications': {
    icon: <Bell className="h-10 w-10" />,
    title: 'All caught up',
    description: 'You have no notifications. New activity will appear here.',
  },
  'no-favorites': {
    icon: <Star className="h-10 w-10" />,
    title: 'No favorites yet',
    description: 'Star items from other pages to save them here for quick access.',
  },
  'no-quality': {
    icon: <BarChart3 className="h-10 w-10" />,
    title: 'No quality analysis',
    description: 'Run a quality analysis to see data quality metrics.',
  },
  'no-mapping': {
    icon: <GitCompareArrows className="h-10 w-10" />,
    title: 'No mappings',
    description: 'Start mapping source values to standard concepts.',
  },
  'no-access': {
    icon: <Shield className="h-10 w-10" />,
    title: 'No access',
    description: 'You do not have permission to view this content.',
  },
  'no-files': {
    icon: <FolderOpen className="h-10 w-10" />,
    title: 'No files',
    description: 'No files or datasets are available.',
  },
};

export function Empty({ icon, description, title, children, variant = 'default', className = '' }: EmptyProps) {
  const config = variantConfig[variant] || variantConfig.default;
  const displayIcon = icon || config.icon;
  const displayTitle = title || config.title;
  const displayDescription = description || config.description;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className={`flex flex-col items-center justify-center py-10 text-center ${className}`}
    >
      {/* Animated icon with floating ring */}
      <div className="relative mb-5">
        <motion.div
          animate={{ y: [0, -4, 0] }}
          transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          className="text-text-dim/50"
        >
          {displayIcon}
        </motion.div>
        {/* Subtle glow ring */}
        <div className="absolute inset-0 -m-3 rounded-full bg-emerald-accent/5 blur-md" />
      </div>
      <h4 className="text-sm font-semibold text-text-muted mb-1">{displayTitle}</h4>
      <p className="text-xs text-text-dim max-w-[280px] mb-4">{displayDescription}</p>
      {children}
    </motion.div>
  );
}
