// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';
import {AdminRewardsPage,CreatorEarningsPage} from './Rewards';

const api=vi.hoisted(()=>({summary:vi.fn(),creatorRewards:vi.fn(),ledger:vi.fn(),adminRewards:vi.fn(),rules:vi.fn(),toggleRule:vi.fn(),action:vi.fn(),createRule:vi.fn()}));
vi.mock('../services/api',async importOriginal=>{const original=await importOriginal<typeof import('../services/api')>();return {...original,getCreatorEarningsSummary:api.summary,getCreatorRewards:api.creatorRewards,getCreatorLedger:api.ledger,getAdminRewards:api.adminRewards,getAdminRewardRules:api.rules,setAdminRewardRuleActive:api.toggleRule,runAdminRewardAction:api.action,createAdminRewardRule:api.createRule,authErrorMessage:(_error:unknown,fallback:string)=>fallback};});
const simulated={id:4,order_id:'CR-TEST123',creator_id:8,brand_id:2,campaign_id:5,campaign:'Glow Campaign',conversion_id:3,product_id:11,products:[{order_item_id:9,product_id:11,product_name:'Cedar Serum',quantity:1,line_total:'100.00'}],reward_rule_id:2,reward_type:'percentage',reward_rate:'10.000',fixed_amount:null,amount:'10.00',eligible_amount:'100.00',excluded_amount:'0.00',currency:'INR',formula:'100.00 * 10.000 / 100',rounding_rule:'ROUND_HALF_UP',calculation_snapshot:{},status:'simulated',risk_status:'clear',is_demo:true,payment_method:'demo',payment_status:'paid',order_status:'confirmed',eligible_at:'2026-12-25T00:00:00Z',created_at:'2026-11-25T00:00:00Z',updated_at:null,payable:false,payout_disclosure:'CROWND does not transfer money.'};
function mount(node:ReactNode){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);}
const notify=vi.fn();
beforeEach(()=>{vi.clearAllMocks();api.summary.mockResolvedValue({pending_collection:'0.00',pending:'0.00',approved:'0.00',simulated_rewards:'10.00',net_actual_reward_liability:'0.00'});api.creatorRewards.mockResolvedValue({items:[simulated],total:1,page:1,page_size:25,pages:1});api.ledger.mockResolvedValue({items:[],total:0,page:1,pages:0});api.adminRewards.mockResolvedValue({items:[simulated],total:1,page:1,page_size:20,pages:1,summary:{net_actual_reward_liability:'0.00',pending_collection:'0.00',under_review:'0.00',simulated_rewards:'10.00',disclosure:'No transfers.'}});api.rules.mockResolvedValue({items:[],total:0,page:1,pages:0});api.action.mockResolvedValue({});api.createRule.mockResolvedValue({});});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe('Phase 5 reward surfaces',()=>{
  it('shows creator reward snapshots and clearly labels demo amounts as non-payable',async()=>{
    mount(<CreatorEarningsPage/>);
    expect(await screen.findByText('Earnings & reward history')).toBeTruthy();
    expect(await screen.findByText('SIMULATED · NOT PAYABLE')).toBeTruthy();
    expect(screen.getByText(/CROWND does not transfer money/)).toBeTruthy();
    expect(screen.queryByRole('button',{name:/payout/i})).toBeNull();
  });
  it('keeps simulated demo rewards out of admin approval and payout actions',async()=>{
    const ui=userEvent.setup();vi.stubGlobal('confirm',vi.fn(()=>true));
    mount(<AdminRewardsPage notify={notify}/>);
    expect(await screen.findByText('Reward operations')).toBeTruthy();
    expect(await screen.findByText('simulated')).toBeTruthy();
    expect(screen.getByText((_text,element)=>element?.tagName==='SMALL'&&element.textContent?.includes('not payable')===true)).toBeTruthy();
    expect(screen.queryByRole('button',{name:'Approve'})).toBeNull();
    expect(screen.queryByRole('button',{name:/Record simulation/})).toBeNull();
    expect(screen.getByText(/no action on this screen transfers funds/i)).toBeTruthy();
    await ui.type(screen.getByPlaceholderText('Order ID, creator name, or email'),'CR-TEST');
    await waitFor(()=>expect(api.adminRewards).toHaveBeenLastCalledWith(expect.objectContaining({q:'CR-TEST'})));
  });
});
