import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LandedCostCard } from '@/components/command-center/LandedCostCard';
import type { LandedCostResult } from '@/types/api';

describe('LandedCostCard', () => {
  it('renders shipment summary, brokerage lines, and commodity breakdown', () => {
    const data: LandedCostResult = {
      action: 'landed_cost',
      success: true,
      totalLandedCost: '786.65',
      currencyCode: 'GBP',
      shipmentId: 'ShipmentID83',
      importCountryCode: 'GB',
      totalDuties: '60',
      totalVAT: '702',
      totalDutyAndTax: '762',
      totalCommodityLevelTaxesAndFees: '0',
      totalShipmentLevelTaxesAndFees: '0',
      totalBrokerageFees: '24.65',
      transId: '325467165',
      brokerageFeeItems: [
        { chargeName: 'DisbursementFee', chargeAmount: '19.05' },
        { chargeName: 'EntryPreparationFee', chargeAmount: '5.60' },
      ],
      requestSummary: {
        exportCountryCode: 'US',
        importCountryCode: 'GB',
        currencyCode: 'GBP',
        shipmentType: 'Sale',
        commodityCount: 2,
        totalUnits: 924,
        declaredMerchandiseValue: '3450.00',
      },
      items: [
        {
          commodityId: '1',
          itemLabel: 'Machinery parts',
          duties: '60',
          taxes: '612',
          fees: '0',
          totalDutyAndTax: '672',
          isCalculable: true,
          hsCode: '4009320090',
        },
        {
          commodityId: '4',
          duties: '0',
          taxes: '90',
          fees: '0',
          totalDutyAndTax: '90',
          isCalculable: false,
          hsCode: '8546901000',
        },
      ],
    };

    render(<LandedCostCard data={data} />);

    expect(screen.getByText('Landed Cost Estimate')).toBeTruthy();
    expect(screen.getByText('Route')).toBeTruthy();
    expect(screen.getByText('US -> GB')).toBeTruthy();
    expect(screen.getByText('Brokerage Fees')).toBeTruthy();
    expect(screen.getByText('DisbursementFee')).toBeTruthy();
    expect(screen.getByText('EntryPreparationFee')).toBeTruthy();
    expect(screen.getByText('Total Landed Cost')).toBeTruthy();
    expect(screen.getByText('Duty + Tax Total')).toBeTruthy();
    expect(screen.getByText('Commodity Tax/Fee')).toBeTruthy();
    expect(screen.getByText('Shipment Tax/Fee')).toBeTruthy();
    expect(screen.getByText('Trans ID')).toBeTruthy();
    expect(screen.getByText('325467165')).toBeTruthy();
    expect(screen.getByText('Machinery parts')).toBeTruthy();
    expect(screen.getByText('#1')).toBeTruthy();
    expect(screen.getByText('#4')).toBeTruthy();
  });

  it('copies shipment ID to clipboard', async () => {
    const writeText = async (_text: string) => Promise.resolve();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    const spy = vi.spyOn(navigator.clipboard, 'writeText');

    const data: LandedCostResult = {
      action: 'landed_cost',
      success: true,
      totalLandedCost: '786.65',
      currencyCode: 'GBP',
      shipmentId: 'ShipmentID83',
      items: [],
    };

    render(<LandedCostCard data={data} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy shipment ID' }));

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith('ShipmentID83');
      expect(screen.getByRole('button', { name: 'Copy shipment ID' }).textContent).toBe('Copied');
    });
  });

  it('handles minimal payloads without request summary', () => {
    const data: LandedCostResult = {
      action: 'landed_cost',
      success: true,
      totalLandedCost: '45.23',
      currencyCode: 'USD',
      items: [
        { commodityId: '1', duties: '12.50', taxes: '7.73', fees: '0.00' },
      ],
    };

    render(<LandedCostCard data={data} />);

    expect(screen.getByText('Landed Cost Estimate')).toBeTruthy();
    expect(screen.getByText('Total Landed Cost')).toBeTruthy();
    expect(screen.getByText('#1')).toBeTruthy();
  });
});
