import {describe,it,expect} from 'vitest';
import {creatorReward,money,moneyExact} from './utils';
describe('financial display helpers',()=>{
  it('calculates percentage rewards with paise precision',()=>expect(creatorReward(2000,10)).toBe(200));
  it('supports a fixed reward',()=>expect(creatorReward(2000,15,'fixed')).toBe(15));
  it('formats INR',()=>expect(money(2000)).toContain('2,000'));
  it('preserves paise for customer catalog and checkout amounts',()=>expect(moneyExact('19.99')).toContain('19.99'));
});
