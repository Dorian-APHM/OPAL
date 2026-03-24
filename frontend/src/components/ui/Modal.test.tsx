import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Modal, Confirm } from './Modal';

describe('Modal', () => {
  it('renders title and children when open', () => {
    render(
      <Modal open={true} onClose={() => {}} title="Test Modal">
        <p>Modal content</p>
      </Modal>
    );
    expect(screen.getByText('Test Modal')).toBeInTheDocument();
    expect(screen.getByText('Modal content')).toBeInTheDocument();
  });

  it('close button has aria-label', () => {
    render(
      <Modal open={true} onClose={() => {}} title="Test">
        Content
      </Modal>
    );
    const closeBtn = screen.getByLabelText('Close');
    expect(closeBtn).toBeInTheDocument();
  });

  it('does not render when closed', () => {
    render(
      <Modal open={false} onClose={() => {}} title="Hidden">
        Content
      </Modal>
    );
    expect(screen.queryByText('Hidden')).toBeNull();
  });

  it('renders footer when provided', () => {
    render(
      <Modal open={true} onClose={() => {}} title="With Footer" footer={<button>Save</button>}>
        Content
      </Modal>
    );
    expect(screen.getByText('Save')).toBeInTheDocument();
  });
});

describe('Confirm', () => {
  it('renders title and buttons when open', () => {
    const onConfirm = vi.fn();
    render(
      <Confirm open={true} onClose={() => {}} onConfirm={onConfirm} title="Delete?" confirmText="Delete" />
    );
    expect(screen.getByText('Delete?')).toBeInTheDocument();
    expect(screen.getByText('Delete')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('renders description when provided', () => {
    render(
      <Confirm open={true} onClose={() => {}} onConfirm={() => {}} title="Sure?" description="This cannot be undone" />
    );
    expect(screen.getByText('This cannot be undone')).toBeInTheDocument();
  });
});
