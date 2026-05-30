import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Table } from './Table';

const columns = [{ title: 'Name', dataIndex: 'name', key: 'name' }];
const rows = [{ name: 'row' }];

describe('Table pagination', () => {
  it('exposes prev/next controls and reports page changes', () => {
    const onChange = vi.fn();
    render(
      <Table
        dataSource={rows}
        columns={columns}
        rowKey={(_: any, i?: number) => String(i)}
        pagination={{ pageSize: 50, total: 500, current: 1, onChange }}
      />,
    );
    fireEvent.click(screen.getByLabelText('Next page'));
    expect(onChange).toHaveBeenCalledWith(2);
  });

  it('keeps pages beyond the 7th reachable via a sliding window', () => {
    render(
      <Table
        dataSource={rows}
        columns={columns}
        rowKey={(_: any, i?: number) => String(i)}
        pagination={{ pageSize: 50, total: 500, current: 8, onChange: () => {} }}
      />,
    );
    // total = 10 pages; window around page 8 should include the last page...
    expect(screen.getByText('10')).toBeInTheDocument();
    // ...and have scrolled past the first pages.
    expect(screen.queryByText('1')).toBeNull();
  });
});
