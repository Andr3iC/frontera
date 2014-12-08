from scrapy.http.request import Request as ScrapyRequest
from scrapy.http.response import Response as ScrapyResponse

from crawlfrontier.core.manager import FrontierManager
from crawlfrontier.core.models import Request as FrontierRequest
from crawlfrontier.core.models import Response as FrontierResponse


class RequestConversor():
    @classmethod
    def scrapy_to_frontier(cls, scrapy_request):
        if isinstance(scrapy_request.cookies, dict):
            cookies = scrapy_request.cookies
        else:
            cookies = dict(sum([d.items() for d in scrapy_request.cookies], []))
        return FrontierRequest(url=scrapy_request.url,
                               method=scrapy_request.method,
                               headers=scrapy_request.headers,
                               cookies=cookies,
                               meta=scrapy_request.meta)

    @classmethod
    def frontier_to_scrapy(cls, frontier_request):
        return ScrapyRequest(url=frontier_request.url,
                             method=frontier_request.method,
                             headers=frontier_request.headers,
                             cookies=frontier_request.cookies,
                             meta={'frontier_request': frontier_request},
                             dont_filter=True)


class ResponseConversor():
    @classmethod
    def scrapy_to_frontier(cls, scrapy_response):
        return FrontierResponse(url=scrapy_response.url,
                                status_code=scrapy_response.status,
                                headers=scrapy_response.headers,
                                body=scrapy_response.body,
                                request=scrapy_response.meta['frontier_request'])

    @classmethod
    def frontier_to_scrapy(cls, frontier_response):
        return ScrapyResponse(url=frontier_response.url,
                              status=frontier_response.status,
                              headers=frontier_response.headers,
                              body=frontier_response.body,
                              request=RequestConversor.frontier_to_scrapy(frontier_response.request))


class ScrapyFrontierManager(object):

    def __init__(self, settings):
        self.manager = FrontierManager.from_settings(settings)

    def start(self, **kwargs):
        self.manager.start(**kwargs)

    def stop(self):
        self.manager.stop()

    def add_seeds(self, scrapy_seeds):
        frontier_seeds = [RequestConversor.scrapy_to_frontier(scrapy_seed) for scrapy_seed in scrapy_seeds]
        self.manager.add_seeds(seeds=frontier_seeds)

    def get_next_requests(self, max_next_requests=0):
        frontier_requests = self.manager.get_next_requests(max_next_requests=max_next_requests)
        return [RequestConversor.frontier_to_scrapy(frontier_request) for frontier_request in frontier_requests]

    def page_crawled(self, scrapy_response, scrapy_links=None):
        frontier_response = ResponseConversor.scrapy_to_frontier(scrapy_response)
        frontier_links = [RequestConversor.scrapy_to_frontier(scrapy_link) for scrapy_link in scrapy_links]
        self.manager.page_crawled(response=frontier_response,
                                  links=frontier_links)

    def request_error(self, scrapy_request, error):
        self.manager.request_error(request=RequestConversor.scrapy_to_frontier(scrapy_request),
                                   error=error)
