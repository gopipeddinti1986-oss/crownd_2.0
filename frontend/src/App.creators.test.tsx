// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {CreatorsPage} from './App';
const getMock=vi.hoisted(()=>vi.fn());
vi.mock('./services/api',async importOriginal=>{const original=await importOriginal<typeof import('./services/api')>();return {...original,api:{get:getMock}};});
const creator={user_id:5,name:'Creator',username:'creator_5',niche:'Food',location:'India',bio:'Real profile',platform:'Instagram',followers:1200,engagement:3.4,availability:true};
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}><CreatorsPage/></QueryClientProvider>);}
describe('creator discovery integration states',()=>{beforeEach(()=>getMock.mockReset());afterEach(()=>cleanup());
 it('loads saved profiles and sends the searchable platform text to the API',async()=>{getMock.mockResolvedValue({data:[creator]});mount();expect(await screen.findByText('Real profile')).toBeTruthy();fireEvent.change(screen.getByLabelText('Search creators'),{target:{value:'Instagram'}});await waitFor(()=>expect(getMock).toHaveBeenLastCalledWith('/creators',{params:{q:'Instagram'}}));});
 it('shows a recoverable error rather than a false empty state',async()=>{getMock.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({data:[creator]});mount();expect(await screen.findByRole('alert')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Retry'}));expect(await screen.findByText('Real profile')).toBeTruthy();});
});
