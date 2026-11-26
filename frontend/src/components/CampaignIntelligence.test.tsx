// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';
import {AdminIntelligenceDashboard,BrandCampaignWorkspace,BrandIntelligenceDashboard,CampaignAnalyticsPage} from './CampaignIntelligence';

const mocks=vi.hoisted(()=>({overview:vi.fn(),campaigns:vi.fn(),creators:vi.fn(),products:vi.fn(),detail:vi.fn(),analytics:vi.fn(),create:vi.fn(),update:vi.fn(),status:vi.fn(),csv:vi.fn(),get:vi.fn()}));
vi.mock('../services/api',async importOriginal=>{const original=await importOriginal<typeof import('../services/api')>();return {...original,getBrandAnalyticsOverview:mocks.overview,getBrandCampaigns:mocks.campaigns,getBrandCreatorPerformance:mocks.creators,getBrandProductPerformance:mocks.products,getCampaignDetail:mocks.detail,getCampaignAnalytics:mocks.analytics,createCampaign:mocks.create,updateCampaign:mocks.update,updateCampaignStatus:mocks.status,downloadBrandAnalyticsCsv:mocks.csv,api:{get:mocks.get}};});
const campaign={id:12,title:'Actual campaign',slug:'actual-campaign',description:'A measured brief',category:'Beauty',platforms:'Instagram',reward_model:'percentage',reward_rate:'10.000',budget:'500.00',status:'published',starts_at:'2026-11-01T00:00:00Z',ends_at:'2026-12-01T00:00:00Z',objectives:['Confirmed sales'],target_audience:'Skincare buyers',creator_requirements:'Original media',visibility:'public',performance_goals:{confirmed_conversions:'4'},product_ids:[7],products:[{id:7,name:'Serum',category:'Beauty'}],accepted_creator_count:2,metrics:{clicks:25,orders:4,confirmed_orders:2,confirmed_revenue:'400.00',pending_revenue:'100.00',generated_reward_value:'40.00',simulated:'0.00'},created_at:'2026-11-01T00:00:00Z'};
const metrics={orders:4,pending_orders:1,confirmed_orders:2,cancelled_orders:1,reversed_orders:0,simulated_orders:0,cod_orders:4,demo_orders:0,gross_attributed_order_value:'500.00',attributed_revenue:'500.00',confirmed_revenue:'400.00',pending_revenue:'100.00',cancelled_revenue:'30.00',reversed_revenue:'0.00',simulated_revenue:'0.00',clicks:25,unique_visitors:20,product_views:10,cart_additions:5,click_to_order_rate_pct:'16.00',click_to_confirmed_rate_pct:'8.00',conversion_rate_pct:'10.00',visitor_to_order_rate_pct:'20.00',cancellation_rate_pct:'25.00',reversal_rate_pct:'0.00',average_order_value:'200.00',revenue_per_click:'16.00',pending:'10.00',under_review:'0.00',eligible:'0.00',approved:'30.00',reversed:'0.00',rejected:'0.00',simulated:'0.00',generated_reward_value:'40.00',reward_records:3,reward_efficiency:{available:true,ratio:'10.00',definition:'Revenue / eligible rewards'},roi:{available:false,reason:'No recorded campaign costs.',roi_pct:null,revenue_to_cost_ratio:null,cost_per_conversion:null}};
const report={campaign:{...campaign,name:campaign.title,creator_count:2,active_creators:1,budget_ceiling:'500.00'},window:{period:'last30',start:'2026-10-27T00:00:00Z',end_exclusive:'2026-11-26T00:00:00Z'},metrics,creators:[{campaign_id:12,campaign:'Actual campaign',creator_id:3,creator:'Creator One',clicks:25,orders:4,confirmed_orders:2,conversion_rate_pct:'10.00',confirmed_revenue:'400.00',average_order_value:'200.00',reward_records:3,reward_value:'40.00',pending_rewards:'10.00',approved_rewards:'30.00',simulated_rewards:'0.00',cancelled_orders:1,cancellation_rate_pct:'25.00'}],products:[{campaign_id:12,campaign:'Actual campaign',product_id:7,product:'Serum',category:'Beauty',clicks:10,orders:3,confirmed_orders:2,conversion_rate_pct:'20.00',confirmed_revenue:'400.00',average_order_value:'200.00',reward_records:3,reward_value:'40.00',pending_rewards:'10.00',approved_rewards:'30.00',simulated_rewards:'0.00',cancelled_orders:1,cancellation_rate_pct:'25.00'}],trends:[{date:'2026-11-25',confirmed_orders:2,confirmed_revenue:'400.00',clicks:25}],funnel:[{stage:'Referral clicks',count:25},{stage:'Unique visitors',count:20},{stage:'Product views',count:10},{stage:'Cart additions',count:5},{stage:'Orders',count:4},{stage:'Confirmed conversions',count:2}],insights:[{type:'product_revenue_leader',subject:'Serum',text:'Highest confirmed attributed revenue.',rule:'max confirmed_revenue'}]};
function mount(node:ReactNode){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);}
const notify=vi.fn();
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});mocks.overview.mockResolvedValue({window:{period:'last30',start:null,end_exclusive:null,timezone:'UTC'},campaigns:{total:1,active:1,completed:0,paused:0,draft:0,by_status:{published:1}},creators:{participating:2,generating_confirmed_conversions:1,ranking:'verified results'},metrics,campaign_comparison:[{campaign_id:12,campaign:'Actual campaign',status:'published',metrics}],});mocks.campaigns.mockResolvedValue({items:[campaign],total:1,page:1,pages:1});mocks.creators.mockResolvedValue({items:report.creators,total:1,page:1,pages:1});mocks.products.mockResolvedValue({items:report.products,total:1,page:1,pages:1});mocks.detail.mockResolvedValue(campaign);mocks.analytics.mockResolvedValue(report);mocks.create.mockResolvedValue({id:14,status:'draft'});mocks.update.mockResolvedValue(campaign);mocks.status.mockResolvedValue({id:12,status:'paused'});mocks.csv.mockResolvedValue(new Blob(['campaign']));mocks.get.mockResolvedValue({data:{items:[{id:7,name:'Serum',category:'Beauty'}]}});});
afterEach(()=>cleanup());

describe('Phase 6 campaign intelligence UI',()=>{
  it('renders real brand KPI values, date controls, and unavailable ROI disclosure',async()=>{
    mount(<BrandIntelligenceDashboard notify={notify}/>);
    expect(await screen.findByText('Brand intelligence')).toBeTruthy();
    expect((await screen.findAllByText('₹400')).length).toBeGreaterThan(0);
    expect(screen.getByText(/ROI and cost per conversion are unavailable/i)).toBeTruthy();
    expect(screen.getByLabelText('Reporting window')).toBeTruthy();
    expect(mocks.overview).toHaveBeenCalledWith(expect.objectContaining({period:'last30'}));
  });
  it('filters campaigns server-side and performs lifecycle transitions',async()=>{
    const user=userEvent.setup();mount(<BrandCampaignWorkspace notify={notify}/>);
    expect(await screen.findByText('Actual campaign')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'Pause'}));
    await waitFor(()=>expect(mocks.status).toHaveBeenCalledWith(12,'paused'));
    fireEvent.change(screen.getByLabelText('Campaign status filter'),{target:{value:'paused'}});
    await waitFor(()=>expect(mocks.campaigns).toHaveBeenLastCalledWith(expect.objectContaining({status:'paused'})));
  });
  it('shows campaign-level funnel and rule-based insight without presenting ROI as available',async()=>{
    mount(<CampaignAnalyticsPage campaignId={12} onBack={vi.fn()}/>);
    expect(await screen.findByText('Confirmed revenue trend')).toBeTruthy();
    expect(screen.getAllByText('Product views').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Cart additions').length).toBeGreaterThan(0);
    expect(screen.getByText(/highest confirmed attributed revenue/i)).toBeTruthy();
    await waitFor(()=>expect(mocks.analytics).toHaveBeenCalledWith(12,expect.objectContaining({period:'last30'})));
  });
  it('renders admin-only aggregate creator and campaign performance summaries',async()=>{
    mocks.get.mockResolvedValueOnce({data:{scope:'platform',brand_id:null,campaign_id:null,campaigns:{total:1,by_status:{published:1},comparison:[{campaign_id:12,campaign:'Actual campaign',status:'published',metrics}]},creators:{total_platform_creators:42,generating_confirmed_conversions:1},metrics,filters:{},customer_data_excluded:true}});
    mount(<AdminIntelligenceDashboard/>);
    expect(await screen.findByText('Campaign lifecycle & results')).toBeTruthy();
    expect(screen.getByText(/42 platform creators/)).toBeTruthy();
    expect(screen.getByText('Actual campaign')).toBeTruthy();
    expect(screen.getAllByText('₹400').length).toBeGreaterThan(0);
  });
  it('provides actionable empty and error states rather than demo analytics',async()=>{
    mocks.overview.mockRejectedValueOnce(new Error('network'));mount(<BrandIntelligenceDashboard notify={notify}/>);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByText('9,999')).toBeNull();
  });
});
