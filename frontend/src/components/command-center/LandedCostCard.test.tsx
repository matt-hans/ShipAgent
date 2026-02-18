import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
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
      totalBrokerageFees: '24.65',
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
        { commodityId: '1', duties: '60', taxes: '612', fees: '0', hsCode: '4009320090' },
        { commodityId: '4', duties: '0', taxes: '90', fees: '0', hsCode: '8546901000' },
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
    expect(screen.getByText('#1')).toBeTruthy();
    expect(screen.getByText('#4')).toBeTruthy();
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
