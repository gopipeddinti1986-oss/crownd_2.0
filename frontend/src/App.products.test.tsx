// @vitest-environment jsdom
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import {ProductsPage} from './App';

const getMock=vi.hoisted(()=>vi.fn());const postMock=vi.hoisted(()=>vi.fn());const patchMock=vi.hoisted(()=>vi.fn());
vi.mock('./services/api',async importOriginal=>{const original=await importOriginal<typeof import('./services/api')>();return {...original,api:{get:getMock,post:postMock,patch:patchMock}};});
const brand={id:9,name:'Catalog Brand',email:'brand@example.com',role:'brand' as const};
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});const notify=vi.fn();return {notify,...render(<QueryClientProvider client={client}><ProductsPage user={brand} notify={notify}/></QueryClientProvider>)};}
const product={id:2,name:'Cedar Serum',category:'Beauty',description:'A serum',price:'100.00',sale_price:'80.00',stock:8,status:'active',image_url:'',image_urls:[],specifications:{},brand:{id:9,name:'Catalog Brand'}};
describe('brand product management integration',()=>{
 beforeEach(()=>{getMock.mockReset();postMock.mockReset();patchMock.mockReset();getMock.mockResolvedValue({data:{items:[product],total:1,page:1,pages:1}});patchMock.mockResolvedValue({data:{...product,stock:15}});});
 it('loads the owner catalog, edits product details, and refreshes cached data',async()=>{mount();expect(await screen.findByText('Cedar Serum')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Edit product'}));fireEvent.change(screen.getByLabelText('Stock quantity'),{target:{value:'15'}});fireEvent.click(screen.getByRole('button',{name:'Save changes'}));await waitFor(()=>expect(patchMock).toHaveBeenCalledWith('/brand/products/2',expect.objectContaining({stock:15,name:'Cedar Serum'})));});
 it('deactivates a product through the status endpoint',async()=>{mount();await screen.findByText('Cedar Serum');fireEvent.click(screen.getByRole('button',{name:'Deactivate'}));await waitFor(()=>expect(patchMock).toHaveBeenCalledWith('/brand/products/2/status',{status:'inactive'}));});
});
