// @vitest-environment jsdom
import type {ComponentProps} from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {Dashboard} from './App';

const apiGet=vi.hoisted(()=>vi.fn());
const getNotificationsMock=vi.hoisted(()=>vi.fn());
vi.mock('./services/api',async importOriginal=>{
  const original=await importOriginal<typeof import('./services/api')>();
  return {...original,api:{get:apiGet},getNotifications:getNotificationsMock,getCreatorEarningsSummary:vi.fn().mockResolvedValue({pending:'0',net_actual_reward_liability:'0'})};
});

const brand={id:1,name:'Audit Brand',email:'brand@example.com',role:'brand' as const};
function renderDashboard(overrides:Partial<ComponentProps<typeof Dashboard>>={}){
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  const props:ComponentProps<typeof Dashboard>={
    user:brand,metrics:{campaigns:0,clicks:0,orders:0,revenue:0},metricsLoading:false,metricsError:false,retryMetrics:vi.fn(),
    campaigns:[],campaignsLoading:false,campaignsError:false,retryCampaigns:vi.fn(),navigate:vi.fn(),...overrides,
  };
  return {client,...render(<QueryClientProvider client={client}><Dashboard {...props}/></QueryClientProvider>)};
}

describe('dashboard uses account data without demo fallbacks',()=>{
  afterEach(()=>cleanup());
  beforeEach(()=>{apiGet.mockReset();apiGet.mockResolvedValue({data:[]});getNotificationsMock.mockReset();getNotificationsMock.mockResolvedValue({items:[],total:0,unread_count:0,page:1,page_size:20,pages:0});});

  it('shows a real empty state rather than inventing sample campaigns',async()=>{
    renderDashboard();
    expect(await screen.findByText('No published campaigns yet.')).toBeTruthy();
    expect(screen.queryByText('The Everyday Ritual')).toBeNull();
    expect(screen.queryByText('Carry Your Day')).toBeNull();
    expect(screen.getByText('Paid-order revenue over the last 7 months')).toBeTruthy();
  });

  it('renders actual notification activity and follows its server-provided action path',async()=>{
    getNotificationsMock.mockResolvedValue({items:[{id:9,category:'order',title:'Order update',body:'Order CR-123 was delivered.',action_path:'/orders/CR-123',read_at:null,created_at:'2026-01-01T00:00:00Z'}],total:1,unread_count:1,page:1,page_size:20,pages:1});
    const navigate=vi.fn();
    renderDashboard({navigate});
    expect(await screen.findByText('Order update')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'View'}));
    expect(navigate).toHaveBeenCalledWith('/orders/CR-123');
  });

  it('distinguishes loading and failed metrics from legitimate zero values',async()=>{
    renderDashboard({metrics:null,metricsLoading:true,campaignsLoading:true,campaigns:undefined});
    expect(screen.getByText('Loading published campaigns…')).toBeTruthy();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('reports failed queries and invokes explicit retry actions',async()=>{
    const retryCampaigns=vi.fn();const retryMetrics=vi.fn();
    renderDashboard({metrics:null,metricsError:true,campaignsError:true,campaigns:undefined,retryCampaigns,retryMetrics});
    expect(await screen.findByText('Campaigns could not be loaded.')).toBeTruthy();
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button',{name:'Retry campaigns'}));
    fireEvent.click(screen.getAllByRole('button',{name:'Refresh metrics'})[0]);
    await waitFor(()=>expect(retryCampaigns).toHaveBeenCalledOnce());
    expect(retryMetrics).toHaveBeenCalledOnce();
  });
});
