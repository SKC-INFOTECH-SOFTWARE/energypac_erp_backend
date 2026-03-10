from rest_framework.pagination import PageNumberPagination


class SmartPageNumberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500

    def get_page_number(self, request, paginator):
        skip = {'page', 'page_size', 'ordering'}
        has_filter = any(k not in skip for k in request.query_params)

        if has_filter and 'page' not in request.query_params:
            return 1

        return super().get_page_number(request, paginator)
