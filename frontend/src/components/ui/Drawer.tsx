import { Fragment, type ReactNode } from 'react';
import { Dialog, DialogPanel, DialogTitle, Transition, TransitionChild } from '@headlessui/react';
import { X } from 'lucide-react';

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  width?: string;
  placement?: 'right' | 'left';
}

export function Drawer({ open, onClose, title, children, width = 'max-w-md', placement = 'right' }: DrawerProps) {
  const isRight = placement === 'right';

  return (
    <Transition show={open} as={Fragment}>
      <Dialog as="div" className="relative z-[1000]" onClose={onClose}>
        <TransitionChild
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-black/40" />
        </TransitionChild>

        <div className="fixed inset-0 overflow-hidden">
          <div className={`absolute inset-y-0 ${isRight ? 'right-0' : 'left-0'} flex max-w-full`}>
            <TransitionChild
              as={Fragment}
              enter="transform transition ease-out duration-300"
              enterFrom={isRight ? 'translate-x-full' : '-translate-x-full'}
              enterTo="translate-x-0"
              leave="transform transition ease-in duration-200"
              leaveFrom="translate-x-0"
              leaveTo={isRight ? 'translate-x-full' : '-translate-x-full'}
            >
              <DialogPanel className={`${width} w-screen bg-surface border-l border-glass-border shadow-[-8px_0_32px_rgba(0,0,0,0.4)] flex flex-col`}>
                {title && (
                  <div className="flex items-center justify-between px-6 py-4 border-b border-glass-border shrink-0">
                    <DialogTitle className="text-base font-semibold text-text-bright">{title}</DialogTitle>
                    <button onClick={onClose} aria-label="Close" className="text-text-dim hover:text-text-muted transition-colors cursor-pointer bg-transparent border-none">
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                )}
                <div className="flex-1 overflow-y-auto p-6">{children}</div>
              </DialogPanel>
            </TransitionChild>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}
