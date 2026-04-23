from django.urls import path

from . import views

app_name = "knowledge"

urlpatterns = [
    # Static pages
    path("", views.index, name="index"),
    path("graph/", views.index, name="graph"),
    path("page/<str:slug>/", views.index, name="page"),
    # Block-centric API endpoints
    path("api/blocks/", views.create_block, name="create_block"),
    path("api/blocks/update/", views.update_block, name="update_block"),
    path("api/blocks/delete/", views.delete_block, name="delete_block"),
    path("api/blocks/reorder/", views.reorder_blocks, name="reorder_blocks"),
    path("api/blocks/toggle-todo/", views.toggle_block_todo, name="toggle_block_todo"),
    path(
        "api/blocks/move-undone-todos/",
        views.move_undone_todos,
        name="move_undone_todos",
    ),
    # Page-centric API endpoints
    path("api/pages/", views.create_page, name="create_page"),
    path("api/pages/update/", views.update_page, name="update_page"),
    path("api/pages/delete/", views.delete_page, name="delete_page"),
    path("api/pages/list/", views.get_pages, name="list_pages"),
    path("api/pages/search/", views.search_pages, name="search_pages"),
    path("api/page/", views.get_page_with_blocks, name="get_page_with_blocks"),
    path("api/historical/", views.get_historical_data, name="get_historical_data"),
    path("api/graph/", views.get_graph_data, name="get_graph_data"),
    path("api/tag/<str:tag_name>/", views.get_tag_content, name="get_tag_content"),
]
