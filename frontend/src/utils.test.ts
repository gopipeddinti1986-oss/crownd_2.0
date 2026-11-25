import {describe,it,expect} from 'vitest';
import {creatorReward,money} from './utils';
describe('financial display helpers',()=>{
  it('calculates percentage rewards with paise precision',()=>expect(creatorReward(2000,10)).toBe(200));
  it('supports a fixed reward',()=>expect(creatorReward(2000,15,'fixed')).toBe(15));
  it('formats INR',()=>expect(money(2000)).toContain('2,000'));
});
