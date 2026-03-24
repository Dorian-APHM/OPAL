import { Fragment, type ReactNode } from 'react';
import { Dialog, DialogPanel, DialogTitle, Transition, TransitionChild } from '@headlessui/react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}

export function Modal({ open, onClose, title, children, footer, width = 'max-w-lg' }: ModalProps) {
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
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" />
        </TransitionChild>

        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <TransitionChild
              as={Fragment}
              enter="ease-out duration-200"
              enterFrom="opacity-0 scale-95"
              enterTo="opacity-100 scale-100"
              leave="ease-in duration-150"
              leaveFrom="opacity-100 scale-100"
              leaveTo="opacity-0 scale-95"
            >
              <DialogPanel className={`${width} w-full bg-surface border border-glass-border rounded-[20px] shadow-[0_20px_60px_rgba(0,0,0,0.5),0_0_40px_rgba(16,185,129,0.08)] transform transition-all`}>
                {title && (
                  <div className="flex items-center justify-between px-6 py-4 border-b border-glass-border">
                    <DialogTitle className="text-base font-semibold text-text-bright">{title}</DialogTitle>
                    <button
                      onClick={onClose}
                      aria-label="Close"
                      className="text-text-dim hover:text-text-muted transition-colors cursor-pointer bg-transparent border-none"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                )}
                <div className="px-6 py-4">{children}</div>
                {footer && (
                  <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-glass-border">
                    {footer}
                  </div>
                )}
              </DialogPanel>
            </TransitionChild>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}

// Simple confirm dialog
interface ConfirmProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  confirmText?: string;
  danger?: boolean;
}

export function Confirm({ open, onClose, onConfirm, title, description, confirmText = 'Confirm', danger = false }: ConfirmProps) {
  return (
    <Modal open={open} onClose={onClose} title={title} width="max-w-sm" footer={
      <>
        <button onClick={onClose} className="px-4 py-2 text-sm text-text-muted bg-surface-light border border-glass-border rounded-lg hover:text-text-bright transition-colors cursor-pointer">
          Cancel
        </button>
        <button
          onClick={() => { onConfirm(); onClose(); }}
          className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors cursor-pointer ${
            danger
              ? 'bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25'
              : 'bg-gradient-to-br from-emerald-accent to-teal-accent text-deep-base'
          }`}
        >
          {confirmText}
        </button>
      </>
    }>
      {description && <p className="text-sm text-text-muted">{description}</p>}
    </Modal>
  );
}
